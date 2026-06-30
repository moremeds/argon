"""Persistence for the exact gap-healer (runs / gaps-only items / caveats /
registry). New domain -> own file (never appended to repository.py)."""

from __future__ import annotations

from datetime import date
from typing import Any

from psycopg import Connection
from psycopg.types.json import Jsonb

from uw_scan.reports.data_gap_healer import (
    Caveat,
    DatasetRegistryEntry,
    GapItem,
)

# Temporal-column predicate, shared by the discovery query. A table is "recorded
# data" if any column looks like a date/time/_at. Mirrors the plan's acceptance
# SQL. Percents are doubled (%%) because this is embedded in a parameterized
# execute; '\_' relies on Postgres LIKE's default backslash escape (literal _).
_TEMPORAL_HAVING = r"""
    bool_or(
        data_type IN (
            'date',
            'timestamp with time zone',
            'timestamp without time zone'
        )
        OR lower(column_name) LIKE '%%date%%'
        OR lower(column_name) LIKE '%%time%%'
        OR lower(column_name) LIKE '%%\_at'
    )
"""


class DataGapHealerRepository:
    def __init__(self, conn: Connection, schema: str = "uw_scan") -> None:
        self._conn = conn
        self._schema = schema
        with conn.cursor() as cur:
            cur.execute(f"SET search_path TO {schema}, public")

    # --- runs -------------------------------------------------------------

    def create_run(
        self,
        *,
        mode: str,
        start_date: date | None,
        end_date: date | None,
        datasets: list[str],
        uw_budget_cap: int | None = None,
        status: str = "running",
        summary: dict[str, Any] | None = None,
    ) -> int:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO data_gap_runs
                    (mode, status, start_date, end_date, datasets,
                     uw_budget_cap, summary_jsonb)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    mode,
                    status,
                    start_date,
                    end_date,
                    datasets,
                    uw_budget_cap,
                    Jsonb(summary or {}),
                ),
            )
            run_id = cur.fetchone()[0]
        self._conn.commit()
        return int(run_id)

    def finish_run(
        self, run_id: int, *, status: str, summary: dict[str, Any] | None = None
    ) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                UPDATE data_gap_runs
                   SET status = %s,
                       finished_at = now(),
                       summary_jsonb = COALESCE(%s, summary_jsonb)
                 WHERE id = %s
                """,
                (status, Jsonb(summary) if summary is not None else None, run_id),
            )
        self._conn.commit()

    def get_run(self, run_id: int) -> dict | None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, started_at, finished_at, mode, status, start_date,
                       end_date, datasets, uw_budget_cap, summary_jsonb, created_by
                  FROM data_gap_runs WHERE id = %s
                """,
                (run_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            cols = [c.name for c in cur.description]
        return dict(zip(cols, row, strict=True))

    def latest_run(self) -> dict | None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, started_at, finished_at, mode, status, summary_jsonb
                  FROM data_gap_runs
                 ORDER BY started_at DESC LIMIT 1
                """
            )
            row = cur.fetchone()
            if row is None:
                return None
            cols = [c.name for c in cur.description]
        return dict(zip(cols, row, strict=True))

    # --- items (gaps-only) ------------------------------------------------

    def upsert_items(self, run_id: int, items: list[GapItem]) -> int:
        if not items:
            return 0
        params = [
            {
                "run_id": run_id,
                "dataset": it.dataset,
                "data_date": it.data_date,
                "ticker": it.ticker,
                "scope_key": it.scope_key,
                "expected_count": it.expected_count,
                "covered_count": it.covered_count,
                "status": it.status,
                "reason": it.reason,
            }
            for it in items
        ]
        sql = """
            INSERT INTO data_gap_items
                (run_id, dataset, data_date, ticker, scope_key,
                 expected_count, covered_count, status, reason)
            VALUES
                (%(run_id)s, %(dataset)s, %(data_date)s, %(ticker)s, %(scope_key)s,
                 %(expected_count)s, %(covered_count)s, %(status)s, %(reason)s)
            ON CONFLICT (run_id, dataset, scope_key) DO UPDATE SET
                data_date      = EXCLUDED.data_date,
                ticker         = EXCLUDED.ticker,
                expected_count = EXCLUDED.expected_count,
                covered_count  = EXCLUDED.covered_count,
                status         = EXCLUDED.status,
                reason         = EXCLUDED.reason
        """
        with self._conn.cursor() as cur:
            cur.executemany(sql, params)
        self._conn.commit()
        return len(params)

    def claim_next_items(
        self,
        run_id: int,
        *,
        limit: int,
        statuses: tuple[str, ...] = ("planned", "skipped_budget", "failed"),
        datasets: list[str] | None = None,
    ) -> list[dict]:
        """Atomically claim up to ``limit`` resumable items, marking them running.

        FOR UPDATE SKIP LOCKED makes this safe against a concurrent run/worker.
        """
        clauses = ["run_id = %s", "status = ANY(%s)"]
        args: list[Any] = [run_id, list(statuses)]
        if datasets:
            clauses.append("dataset = ANY(%s)")
            args.append(datasets)
        where = " AND ".join(clauses)
        args.append(limit)
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE data_gap_items
                   SET status = 'running', attempts = attempts + 1
                 WHERE id IN (
                     SELECT id FROM data_gap_items
                      WHERE {where}
                      ORDER BY data_date NULLS LAST, dataset, ticker
                      LIMIT %s
                      FOR UPDATE SKIP LOCKED
                 )
                RETURNING id, dataset, data_date, ticker, scope_key,
                          expected_count, covered_count, estimated_requests
                """,
                args,
            )
            cols = [c.name for c in cur.description]
            rows = [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]
        self._conn.commit()
        return rows

    def _set_item_status(
        self,
        item_id: int,
        status: str,
        *,
        reason: str | None = None,
        actual_requests: int | None = None,
        last_error: str | None = None,
        verified: bool = False,
    ) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                UPDATE data_gap_items
                   SET status = %s,
                       reason = COALESCE(%s, reason),
                       actual_requests = actual_requests + COALESCE(%s, 0),
                       last_error = %s,
                       verified_at = CASE WHEN %s THEN now() ELSE verified_at END
                 WHERE id = %s
                """,
                (status, reason, actual_requests, last_error, verified, item_id),
            )
        self._conn.commit()

    def mark_item_healed(self, item_id: int, *, actual_requests: int = 0) -> None:
        self._set_item_status(
            item_id, "healed", actual_requests=actual_requests, verified=True
        )

    def mark_item_no_data(
        self, item_id: int, *, reason: str, actual_requests: int = 0
    ) -> None:
        self._set_item_status(
            item_id,
            "no_data",
            reason=reason,
            actual_requests=actual_requests,
            verified=True,
        )

    def mark_item_skipped_budget(self, item_id: int) -> None:
        self._set_item_status(item_id, "skipped_budget", reason="budget cap reached")

    def mark_item_failed(self, item_id: int, *, last_error: str) -> None:
        self._set_item_status(item_id, "failed", last_error=last_error)

    def list_items(self, run_id: int, *, status: str | None = None) -> list[dict]:
        clauses = ["run_id = %s"]
        args: list[Any] = [run_id]
        if status is not None:
            clauses.append("status = %s")
            args.append(status)
        where = " AND ".join(clauses)
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT id, dataset, data_date, ticker, scope_key, expected_count,
                       covered_count, actual_requests, status, reason, attempts,
                       last_error, verified_at
                  FROM data_gap_items
                 WHERE {where}
                 ORDER BY dataset, data_date NULLS LAST, ticker
                """,
                args,
            )
            cols = [c.name for c in cur.description]
            return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]

    def count_items_by_status(self, run_id: int) -> dict[str, int]:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT status, COUNT(*)::int
                  FROM data_gap_items WHERE run_id = %s GROUP BY status
                """,
                (run_id,),
            )
            return {row[0]: row[1] for row in cur.fetchall()}

    # --- caveats ----------------------------------------------------------

    def upsert_caveat(self, cav: Caveat) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO data_gap_caveats
                    (dataset, ticker, start_date, end_date, reason, source)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (dataset, COALESCE(ticker, ''),
                             COALESCE(start_date, DATE '0001-01-01'),
                             COALESCE(end_date, DATE '9999-12-31'), reason)
                DO NOTHING
                """,
                (
                    cav.dataset,
                    cav.ticker,
                    cav.start_date,
                    cav.end_date,
                    cav.reason,
                    cav.source,
                ),
            )
        self._conn.commit()

    def list_caveats(self, dataset: str | None = None) -> list[Caveat]:
        clauses = []
        args: list[Any] = []
        if dataset is not None:
            clauses.append("dataset = %s")
            args.append(dataset)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT dataset, ticker, start_date, end_date, reason, source
                  FROM data_gap_caveats {where}
                 ORDER BY dataset, ticker NULLS FIRST
                """,
                args,
            )
            return [
                Caveat(
                    dataset=r[0],
                    ticker=r[1],
                    start_date=r[2],
                    end_date=r[3],
                    reason=r[4],
                    source=r[5],
                )
                for r in cur.fetchall()
            ]

    # --- dataset registry (projection of the Python REGISTRY) -------------

    def sync_dataset_registry(self, entries: list[DatasetRegistryEntry]) -> int:
        if not entries:
            return 0
        params = [
            {
                "table_name": e.table_name,
                "dataset_group": e.dataset_group,
                "audit_mode": e.audit_mode,
                "date_col": e.date_col,
                "ticker_col": e.ticker_col,
                "expected_frequency": e.expected_frequency,
                "provider": e.provider,
                "granularity": e.granularity,
                "healer_adapter": e.healer_adapter,
                "source_system": e.source_system,
                "retention_days": e.retention_days,
                "enabled": e.enabled,
                "reason": e.reason,
            }
            for e in entries
        ]
        sql = """
            INSERT INTO data_gap_dataset_registry
                (table_name, dataset_group, audit_mode, date_col, ticker_col,
                 expected_frequency, provider, granularity, healer_adapter,
                 source_system, retention_days, enabled, reason)
            VALUES
                (%(table_name)s, %(dataset_group)s, %(audit_mode)s, %(date_col)s,
                 %(ticker_col)s, %(expected_frequency)s, %(provider)s,
                 %(granularity)s, %(healer_adapter)s, %(source_system)s,
                 %(retention_days)s, %(enabled)s, %(reason)s)
            ON CONFLICT (table_name) DO UPDATE SET
                dataset_group      = EXCLUDED.dataset_group,
                audit_mode         = EXCLUDED.audit_mode,
                date_col           = EXCLUDED.date_col,
                ticker_col         = EXCLUDED.ticker_col,
                expected_frequency = EXCLUDED.expected_frequency,
                provider           = EXCLUDED.provider,
                granularity        = EXCLUDED.granularity,
                healer_adapter     = EXCLUDED.healer_adapter,
                source_system      = EXCLUDED.source_system,
                retention_days     = EXCLUDED.retention_days,
                enabled            = EXCLUDED.enabled,
                reason             = EXCLUDED.reason
        """
        with self._conn.cursor() as cur:
            cur.executemany(sql, params)
        self._conn.commit()
        return len(params)

    def list_dataset_registry(self) -> list[dict]:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_name, dataset_group, audit_mode, date_col, ticker_col,
                       expected_frequency, provider, granularity, healer_adapter,
                       source_system, retention_days, enabled, reason
                  FROM data_gap_dataset_registry
                 ORDER BY dataset_group, table_name
                """
            )
            cols = [c.name for c in cur.description]
            return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]

    def list_unregistered_time_tables(self) -> list[str]:
        """Temporal tables in the schema with no registry row (acceptance check).

        Canonical SQL form of the plan's registry-acceptance rule. Returns []
        once every recorded dataset is registered (full coverage gate, T7).
        """
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT table_name
                  FROM information_schema.columns
                 WHERE table_schema = %s
                 GROUP BY table_name
                HAVING {_TEMPORAL_HAVING}
                EXCEPT
                SELECT table_name FROM data_gap_dataset_registry
                 ORDER BY table_name
                """,
                (self._schema,),
            )
            return [r[0] for r in cur.fetchall()]
