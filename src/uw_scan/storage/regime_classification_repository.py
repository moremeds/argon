"""Persistence for VCG regime-classification accuracy reports.

Tags rows with:
    indicator='vcg', composite_method='classification_accuracy',
    credit_proxy='CLASSIFICATION', window_days=1 (placeholder),
    run_scope='research' (Hard Guarantee #2 default-deny gate).

All classification-specific per-day data goes in regime_backtest_daily.payload
JSONB. No new daily columns. Migration 062 unique index prevents concurrent
duplicate inserts (v0.3 / CR-2).

This module does NOT reuse RegimeBacktestRepository's `insert_run` /
`bulk_insert_daily` / `mark_run_completed` because those each commit
internally; for the atomic `insert_complete_run` (v0.3 / CL-8) we
issue the SQL inline within a single `conn.transaction()` block.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from psycopg import Connection
from psycopg.errors import UniqueViolation
from psycopg.types.json import Jsonb


class ClassificationRunAlreadyExists(Exception):
    """Raised when migration 062's unique index rejects a duplicate insert."""


class RegimeClassificationRepository:
    INDICATOR = "vcg"
    COMPOSITE_METHOD = "classification_accuracy"
    RUN_SCOPE = "research"
    CREDIT_PROXY_SENTINEL = "CLASSIFICATION"
    WINDOW_DAYS_PLACEHOLDER = 1

    def __init__(self, conn: Connection, *, schema: str = "uw_scan") -> None:
        self._conn = conn
        self._schema = schema
        with conn.cursor() as cur:
            cur.execute(f"SET search_path TO {schema}, public")

    # ----- Non-atomic helpers (each commits; safe outside transactions) -----

    def insert_classification_run(
        self,
        *,
        vcg_source_run_id: int,
        composite_version: str,
        eval_start: date,
        eval_end: date,
        label_version: int,
        n_days: int,
        summary: dict[str, Any],
        note: str = "",
    ) -> int:
        sql = f"""
            INSERT INTO {self._schema}.regime_backtest_runs (
                indicator, composite_version, start_date, end_date,
                window_days, n_days, params, summary, note,
                run_scope, composite_method, credit_proxy
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """
        params = {
            "vcg_source_run_id": vcg_source_run_id,
            "label_version": label_version,
            "window_days_semantics": "not_applicable_for_classification",
        }
        with self._conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    self.INDICATOR,
                    composite_version,
                    eval_start,
                    eval_end,
                    self.WINDOW_DAYS_PLACEHOLDER,
                    n_days,
                    Jsonb(params),
                    Jsonb(summary),
                    note or f"classification baseline label_version={label_version}",
                    self.RUN_SCOPE,
                    self.COMPOSITE_METHOD,
                    self.CREDIT_PROXY_SENTINEL,
                ),
            )
            row = cur.fetchone()
        assert row is not None
        return int(row[0])

    def bulk_insert_daily_classifications(
        self, run_id: int, rows: list[dict[str, Any]]
    ) -> None:
        if not rows:
            return
        sql = f"""
            INSERT INTO {self._schema}.regime_backtest_daily
                (run_id, trade_date, score, level, payload)
            VALUES (%s, %s, %s, %s, %s)
        """
        params = [
            (
                run_id,
                r["trade_date"],
                float(r.get("score", 0.0)),
                r.get("vcg_label"),
                Jsonb(
                    {
                        "vcg_label": r["vcg_label"],
                        "truth_label": r["truth_label"],
                        "match": bool(r["match"]),
                        "label_components": r.get("label_components", {}),
                        "label_version": r["label_version"],
                    }
                ),
            )
            for r in rows
        ]
        with self._conn.cursor() as cur:
            cur.executemany(sql, params)

    def mark_run_completed(self, run_id: int) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"UPDATE {self._schema}.regime_backtest_runs "
                f"SET completed_at = NOW() WHERE id = %s",
                (run_id,),
            )

    def update_run_summary(self, run_id: int, summary: dict[str, Any]) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"UPDATE {self._schema}.regime_backtest_runs "
                f"SET summary = %s WHERE id = %s",
                (Jsonb(summary), run_id),
            )

    # ----- Atomic API (v0.3 / CL-8) -----

    def insert_complete_run(
        self,
        *,
        vcg_source_run_id: int,
        composite_version: str,
        eval_start: date,
        eval_end: date,
        label_version: int,
        summary: dict[str, Any],
        note: str = "",
        daily_rows: list[dict[str, Any]],
    ) -> int:
        """Atomic insert_run -> bulk_insert -> mark_completed (v0.3 / CL-8).

        Catches UniqueViolation from migration 062's partial index and
        raises ClassificationRunAlreadyExists with a replay hint (CR-2).
        """
        n_days = len(daily_rows)
        try:
            with self._conn.transaction():
                run_id = self.insert_classification_run(
                    vcg_source_run_id=vcg_source_run_id,
                    composite_version=composite_version,
                    eval_start=eval_start,
                    eval_end=eval_end,
                    label_version=label_version,
                    n_days=n_days,
                    summary=summary,
                    note=note,
                )
                self.bulk_insert_daily_classifications(run_id, daily_rows)
                self.mark_run_completed(run_id)
            return run_id
        except UniqueViolation as exc:
            raise ClassificationRunAlreadyExists(
                f"Run for (vcg_source_run_id={vcg_source_run_id}, "
                f"label_version={label_version}) already completed; "
                f"use --render-run-id to replay"
            ) from exc

    # ----- Read paths -----

    def find_completed_classification_run(
        self, *, vcg_source_run_id: int, label_version: int
    ) -> int | None:
        sql = f"""
            SELECT id FROM {self._schema}.regime_backtest_runs
            WHERE indicator = %s
              AND composite_method = %s
              AND run_scope = %s
              AND completed_at IS NOT NULL
              AND archived_at IS NULL
              AND (params->>'vcg_source_run_id')::int = %s
              AND (params->>'label_version')::int = %s
            ORDER BY id DESC LIMIT 1
        """
        with self._conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    self.INDICATOR,
                    self.COMPOSITE_METHOD,
                    self.RUN_SCOPE,
                    vcg_source_run_id,
                    label_version,
                ),
            )
            row = cur.fetchone()
        return int(row[0]) if row else None

    def load_run_for_render(self, run_id: int) -> dict:
        """Reload everything needed for replay (v0.3 / CR-1)."""
        with self._conn.cursor() as cur:
            cur.execute(
                f"SELECT params, summary, start_date, end_date, n_days "
                f"FROM {self._schema}.regime_backtest_runs WHERE id=%s",
                (run_id,),
            )
            head = cur.fetchone()
            if head is None:
                raise ValueError(f"run_id={run_id} not found")
            params, summary, start_date, end_date, n_days = head
            cur.execute(
                f"SELECT trade_date, level, payload "
                f"FROM {self._schema}.regime_backtest_daily "
                f"WHERE run_id=%s ORDER BY trade_date",
                (run_id,),
            )
            daily = cur.fetchall()
        return {
            "params": params,
            "summary": summary,
            "start_date": start_date,
            "end_date": end_date,
            "n_days": n_days,
            "daily": daily,
        }
