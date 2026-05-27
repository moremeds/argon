"""Persistence for CRI/VCG regime backtest runs.

New domain — own module per docs/research/regime/CLAUDE.md and the global
no-extend-repository.py rule. Mirrors the CriSnapshotRepository pattern:
takes a psycopg.Connection + schema string, sets search_path on init.

Two-phase atomic write:
    insert_run() -> bulk_insert_daily() -> mark_run_completed()

find_latest_run filters on completed_at IS NOT NULL so an interrupted
backtest cannot poison /api/regime/validation. It also filters on
composite_version (default = the indicator's current code constant) so
experimental calibrations are query-only via SQL.

Research scope (migration 059): run_scope / composite_method / credit_proxy
are top-level columns. Production reads default run_scope='production' and
(for VCG) credit_proxy='HYG' + composite_method='single_proxy' so the
existing /api/regime/validation call site cannot accidentally surface a
research row.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from psycopg import Connection
from psycopg.types.json import Jsonb


class RegimeBacktestRepository:
    def __init__(self, conn: Connection, schema: str = "uw_scan") -> None:
        self._conn = conn
        self._schema = schema
        with conn.cursor() as cur:
            cur.execute(f"SET search_path TO {schema}, public")

    def insert_run(
        self,
        *,
        indicator: Literal["cri", "vcg", "canary"],
        composite_version: str,
        start_date: date,
        end_date: date,
        window_days: int,
        n_days: int,
        params: dict,
        summary: dict,
        note: str | None = None,
        run_scope: str = "production",
        composite_method: str = "single_proxy",
        credit_proxy: str | None = None,
    ) -> int:
        # Application-level safeguards (Python-side, complementing the SQL
        # CHECK constraints in migration 059). A future caller that forgets to
        # pass run_scope='research' for a composite row would otherwise write
        # a research-shape row tagged as production — Hard Guarantee #4 leak.
        if indicator == "vcg":
            # Mirror migration 059 Phase 2b: VCG rows with no explicit
            # credit_proxy default to 'HYG' so the
            # regime_backtest_runs_vcg_credit_proxy_check CHECK isn't tripped
            # by legacy callers (existing CRI/VCG fixtures predate the
            # migration). Composite/candidate guards still reject mis-tagged
            # research-shape rows below.
            if credit_proxy is None:
                credit_proxy = "HYG"
            if composite_method != "single_proxy" and run_scope != "research":
                raise ValueError(
                    f"VCG composite_method={composite_method!r} requires "
                    f"run_scope='research' (got {run_scope!r})"
                )
            if (
                credit_proxy
                and credit_proxy.startswith("COMPOSITE")
                and run_scope != "research"
            ):
                raise ValueError(
                    f"VCG credit_proxy={credit_proxy!r} requires run_scope='research'"
                )
            if "candidate" in (composite_version or "") and run_scope != "research":
                raise ValueError(
                    f"VCG composite_version={composite_version!r} requires "
                    f"run_scope='research'"
                )

        sql = """
            INSERT INTO regime_backtest_runs (
                indicator, composite_version, start_date, end_date,
                window_days, n_days, params, summary, note,
                run_scope, composite_method, credit_proxy
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """
        with self._conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    indicator,
                    composite_version,
                    start_date,
                    end_date,
                    window_days,
                    n_days,
                    Jsonb(params),
                    Jsonb(summary),
                    note,
                    run_scope,
                    composite_method,
                    credit_proxy,
                ),
            )
            row = cur.fetchone()
        assert row is not None
        self._conn.commit()
        return int(row[0])

    def bulk_insert_daily(self, run_id: int, rows: list[dict]) -> None:
        if not rows:
            return
        sql = """
            INSERT INTO regime_backtest_daily (run_id, trade_date, score, level, payload)
            VALUES (%s, %s, %s, %s, %s)
        """
        params = [
            (
                run_id,
                r["trade_date"],
                r["score"],
                r.get("level"),
                Jsonb(r.get("payload", {})),
            )
            for r in rows
        ]
        with self._conn.cursor() as cur:
            cur.executemany(sql, params)
        self._conn.commit()

    def mark_run_completed(self, run_id: int) -> None:
        """Set completed_at = NOW(). MUST be the last call in a backtest."""
        with self._conn.cursor() as cur:
            cur.execute(
                "UPDATE regime_backtest_runs SET completed_at = NOW() WHERE id = %s",
                (run_id,),
            )
        self._conn.commit()

    def delete_runs_by_batch_id(self, batch_id: str) -> int:
        """Delete canary form_sweep_full research runs with given batch_id.

        Scoped intentionally narrow — only `indicator='canary'`,
        `run_scope='research'`, `params->>'phase'='form_sweep_full'` rows
        are affected. This is the cleanup-on-failure path for
        `cmd_form_sweep_full`; it should never touch any other indicator,
        scope, or phase even on a UUID4 collision.

        Daily rows are removed by ON DELETE CASCADE (migration 057).
        Returns the number of run rows deleted (0 if no match).
        """
        with self._conn.cursor() as cur:
            cur.execute(
                f"DELETE FROM {self._schema}.regime_backtest_runs "
                "WHERE indicator = 'canary' "
                "  AND run_scope = 'research' "
                "  AND params->>'phase' = 'form_sweep_full' "
                "  AND params->>'batch_id' = %s",
                (batch_id,),
            )
            deleted = cur.rowcount
        self._conn.commit()
        return deleted

    def delete_canary_research_runs_by_batch_id_and_phase(
        self, batch_id: str, phase: str
    ) -> int:
        """Delete canary research runs scoped to a specific (batch_id, phase).

        Unlike `delete_runs_by_batch_id` (which hard-pins
        params.phase='form_sweep_full' for PR #88), this method accepts
        an arbitrary phase string. Used by v2-A's cleanup-on-failure paths
        (phase='walk_forward', phase='robustness').

        Scope: indicator='canary' AND run_scope='research' AND
        params->>'phase' = %s AND params->>'batch_id' = %s. Production rows
        are NEVER deleted, even on UUID4 collision.

        Daily rows cascade via ON DELETE CASCADE (migration 057).
        Returns the number of run rows deleted (0 if no match).

        Spec §5.8.
        """
        with self._conn.cursor() as cur:
            cur.execute(
                f"DELETE FROM {self._schema}.regime_backtest_runs "
                "WHERE indicator = 'canary' "
                "  AND run_scope = 'research' "
                "  AND params->>'phase' = %s "
                "  AND params->>'batch_id' = %s",
                (phase, batch_id),
            )
            deleted = cur.rowcount
        self._conn.commit()
        return deleted

    def find_latest_run(
        self,
        indicator: Literal["cri", "vcg", "canary"],
        composite_version: str | None = None,
        *,
        run_scope: str = "production",
        credit_proxy: str | None = None,
        composite_method: str | None = None,
    ) -> dict | None:
        """Latest COMPLETED run for the indicator.

        composite_version defaults to the indicator's current code constant
        when called from the API. Callers wanting experimental rows pass an
        explicit composite_version.

        For VCG production reads (the default), credit_proxy and
        composite_method also default to 'HYG' / 'single_proxy' so the
        existing API call site `find_latest_run("vcg")` cannot accidentally
        surface a non-HYG / non-single-proxy row added under future research
        runs writing into composite_version='1' (Hard Guarantee #2).
        """
        # VCG-specific production defaults. Apply BEFORE composite_version
        # resolution so an explicit composite_version override still picks
        # up HYG/single_proxy automatically.
        if indicator == "vcg" and run_scope == "production":
            if credit_proxy is None:
                credit_proxy = "HYG"
            if composite_method is None:
                composite_method = "single_proxy"

        if composite_version is None:
            composite_version = _current_composite_version(indicator)

        clauses = [
            "indicator = %s",
            "composite_version = %s",
            "completed_at IS NOT NULL",
            "run_scope = %s",
        ]
        params: list[Any] = [indicator, composite_version, run_scope]
        if credit_proxy is not None:
            clauses.append("credit_proxy = %s")
            params.append(credit_proxy)
        if composite_method is not None:
            clauses.append("composite_method = %s")
            params.append(composite_method)

        sql = f"""
            SELECT id, indicator, composite_version, start_date, end_date,
                   window_days, n_days, params, summary, note,
                   run_scope, composite_method, credit_proxy,
                   created_at, completed_at
              FROM regime_backtest_runs
             WHERE {" AND ".join(clauses)}
             ORDER BY created_at DESC
             LIMIT 1
        """
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            cols = [d[0] for d in cur.description] if cur.description else []
        if row is None:
            return None
        return dict(zip(cols, row, strict=True))

    def fetch_daily_for_run(self, run_id: int) -> list[dict]:
        sql = """
            SELECT trade_date, score, level, payload
              FROM regime_backtest_daily
             WHERE run_id = %s
             ORDER BY trade_date
        """
        with self._conn.cursor() as cur:
            cur.execute(sql, (run_id,))
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description] if cur.description else []
        return [dict(zip(cols, r, strict=True)) for r in rows]

    def list_runs(
        self,
        indicator: Literal["cri", "vcg", "canary"],
        limit: int = 20,
        completed_only: bool = True,
    ) -> list[dict]:
        where = "WHERE indicator = %s"
        params: list[Any] = [indicator]
        if completed_only:
            where += " AND completed_at IS NOT NULL"
        sql = f"""
            SELECT id, indicator, composite_version, start_date, end_date,
                   window_days, n_days, params, summary, note,
                   run_scope, composite_method, credit_proxy,
                   created_at, completed_at
              FROM regime_backtest_runs
             {where}
             ORDER BY created_at DESC
             LIMIT %s
        """
        params.append(limit)
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description] if cur.description else []
        return [dict(zip(cols, r, strict=True)) for r in rows]

    def list_research_runs(
        self,
        *,
        indicator: Literal["cri", "vcg"],
        composite_version: str | None = None,
        credit_proxy: str | None = None,
        composite_method: str | None = None,
        completed_only: bool = True,
        limit: int = 200,
    ) -> list[dict]:
        """All research-scope runs matching optional filters.

        Distinct from list_runs: hard-pins run_scope='research'. Used by the
        comparator script to load the full panel of candidate runs without
        risk of pulling in a production row.
        """
        clauses = ["indicator = %s", "run_scope = 'research'"]
        params: list[Any] = [indicator]
        if completed_only:
            clauses.append("completed_at IS NOT NULL")
        if composite_version is not None:
            clauses.append("composite_version = %s")
            params.append(composite_version)
        if credit_proxy is not None:
            clauses.append("credit_proxy = %s")
            params.append(credit_proxy)
        if composite_method is not None:
            clauses.append("composite_method = %s")
            params.append(composite_method)
        sql = f"""
            SELECT id, indicator, composite_version, start_date, end_date,
                   window_days, n_days, params, summary, note,
                   run_scope, composite_method, credit_proxy,
                   created_at, completed_at
              FROM regime_backtest_runs
             WHERE {" AND ".join(clauses)}
             ORDER BY created_at DESC
             LIMIT %s
        """
        params.append(limit)
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description] if cur.description else []
        return [dict(zip(cols, r, strict=True)) for r in rows]


def _current_composite_version(indicator: Literal["cri", "vcg", "canary"]) -> str:
    """Resolve the indicator's current code constant to a string.

    Imported lazily to keep this module dependency-light and avoid a circular
    import (cards/* don't depend on storage/*, and we want to keep it that way).
    """
    if indicator == "cri":
        from uw_scan.cards.cri_scorers import COMPOSITE_VERSION  # noqa: PLC0415

        return str(COMPOSITE_VERSION)
    if indicator == "vcg":
        from uw_scan.cards.vcg_scoring import COMPOSITE_VERSION  # noqa: PLC0415

        return str(COMPOSITE_VERSION)
    if indicator == "canary":
        from uw_scan.cards.canary_calibration import COMPOSITE_VERSION  # noqa: PLC0415

        return str(COMPOSITE_VERSION)
    raise ValueError(f"unknown indicator: {indicator}")
