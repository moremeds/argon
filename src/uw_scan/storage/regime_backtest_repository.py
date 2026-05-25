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
        indicator: Literal["cri", "vcg"],
        composite_version: str,
        start_date: date,
        end_date: date,
        window_days: int,
        n_days: int,
        params: dict,
        summary: dict,
        note: str | None = None,
    ) -> int:
        sql = """
            INSERT INTO regime_backtest_runs (
                indicator, composite_version, start_date, end_date,
                window_days, n_days, params, summary, note
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
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

    def find_latest_run(
        self,
        indicator: Literal["cri", "vcg"],
        composite_version: str | None = None,
    ) -> dict | None:
        """Latest COMPLETED run for the indicator.

        composite_version defaults to the indicator's current code constant
        when called from the API. Callers wanting experimental rows pass an
        explicit composite_version.
        """
        if composite_version is None:
            composite_version = _current_composite_version(indicator)

        sql = """
            SELECT id, indicator, composite_version, start_date, end_date,
                   window_days, n_days, params, summary, note,
                   created_at, completed_at
              FROM regime_backtest_runs
             WHERE indicator = %s
               AND composite_version = %s
               AND completed_at IS NOT NULL
             ORDER BY created_at DESC
             LIMIT 1
        """
        with self._conn.cursor() as cur:
            cur.execute(sql, (indicator, composite_version))
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
        indicator: Literal["cri", "vcg"],
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


def _current_composite_version(indicator: Literal["cri", "vcg"]) -> str:
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
    raise ValueError(f"unknown indicator: {indicator}")
