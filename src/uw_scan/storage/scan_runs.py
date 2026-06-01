"""Scan-run lifecycle, advisory lock, and scan-run JSONB helpers."""

from __future__ import annotations

from datetime import datetime

import psycopg
from psycopg.types.json import Jsonb

from .. import models
from ._helpers import _nullable_float
from .rows import ScanDurationSummaryRow


class _ScanRunsMixin:
    _conn: psycopg.Connection
    _schema: str

    def latest_run_id(self, ticker: str) -> int:
        """Return the highest full-scan run_id for `ticker`, or 0 if none.

        Excludes runs created by side-channel jobs that populate only a
        narrow slice of tables and would otherwise shadow the actual
        full-scan run the report assembler needs (flow_alerts, oi_change_top,
        GEX, volatility — all keyed by run_id). Excluded:

        - ``flow_data_refresh`` (writes options_volume_daily + option_chain only)
        - ``positioning_refresh`` (M4 trade-framework: uw_positioning only)
        - ``intraday_refresh`` (OI movers intraday: option_chain_oi only)
        - ``cockpit_daily_snapshot`` (SPX/SPY/QQQ/IWM greeks/skew only)
        - ``gex_scan_*`` (SPX/SPY index-only GEX scanner running every 5 min)
        """
        with self._conn.cursor() as cur:
            cur.execute(
                f"SELECT run_id FROM {self._schema}.scan_runs "
                "WHERE ticker = %s "
                "  AND (notes IS DISTINCT FROM 'flow_data_refresh') "
                "  AND (notes IS DISTINCT FROM 'positioning_refresh') "
                "  AND (notes IS DISTINCT FROM 'intraday_refresh') "
                "  AND (notes IS DISTINCT FROM 'cockpit_daily_snapshot') "
                "  AND (notes IS NULL OR notes NOT LIKE 'gex_scan_%%') "
                "ORDER BY run_id DESC LIMIT 1",
                (ticker.upper(),),
            )
            row = cur.fetchone()
            return int(row[0]) if row else 0

    def insert_scan_run(self, ticker: str, notes: str = "") -> int:
        sql = (
            f"INSERT INTO {self._schema}.scan_runs (ticker, notes) "
            "VALUES (%s, %s) RETURNING run_id"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker.upper(), notes))
            row = cur.fetchone()
        assert row is not None
        return int(row[0])

    def finish_scan_run(self, run_id: int, status: str = "ok") -> None:
        sql = (
            f"UPDATE {self._schema}.scan_runs "
            "SET finished_at = now(), status = %s WHERE run_id = %s"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (status, run_id))

    def get_scan_duration_summary(
        self, start: datetime, end: datetime
    ) -> ScanDurationSummaryRow:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                    avg(extract(epoch FROM finished_at - started_at)),
                    percentile_cont(0.95) WITHIN GROUP (
                        ORDER BY extract(epoch FROM finished_at - started_at)
                    )
                FROM {self._schema}.scan_runs
                WHERE finished_at >= %s
                  AND finished_at < %s
                  AND finished_at IS NOT NULL
                  AND started_at IS NOT NULL
                  AND status = 'ok'
                  AND (notes IS DISTINCT FROM 'flow_data_refresh')
                  AND (notes IS DISTINCT FROM 'positioning_refresh')
                  AND (notes IS DISTINCT FROM 'intraday_refresh')
                  AND (notes IS DISTINCT FROM 'cockpit_daily_snapshot')
                  AND (notes IS NULL OR notes NOT LIKE 'gex_scan_%%')
                """,
                (start, end),
            )
            row = cur.fetchone()
        return ScanDurationSummaryRow(
            avg_seconds=_nullable_float(row[0]) if row else None,
            p95_seconds=_nullable_float(row[1]) if row else None,
        )

    # ------------------------------------------------------------------
    # advisory locks (single-flight worker jobs)
    # ------------------------------------------------------------------

    def try_advisory_lock(self, key: int) -> bool:
        """Session-scoped ``pg_try_advisory_lock``; returns True if acquired.

        Mirror the precedent in ``api/routers/volatility.py``. Always pair with
        :meth:`release_advisory_lock` in a ``finally`` block.
        """

        with self._conn.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(%s)", (key,))
            row = cur.fetchone()
            return bool(row and row[0])

    def release_advisory_lock(self, key: int) -> None:
        with self._conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock(%s)", (key,))

    # ------------------------------------------------------------------
    # external_api_requests
    # ------------------------------------------------------------------

    def count_rows(self, table: str) -> int:
        sql = f"SELECT COUNT(*) FROM {self._schema}.{table}"
        with self._conn.cursor() as cur:
            cur.execute(sql)
            row = cur.fetchone()
        assert row is not None
        return int(row[0])

    def apply_migration(self, sql_text: str) -> None:
        with self._conn.cursor() as cur:
            cur.execute(sql_text)

    # ------------------------------------------------------------------
    # S2: scan_universe + scan_results
    # ------------------------------------------------------------------

    def set_aggregates(self, run_id: int, agg: "models.MarketAggregates") -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"UPDATE {self._schema}.scan_runs SET aggregates=%s WHERE run_id=%s",
                (Jsonb(agg.model_dump(mode="json")), run_id),
            )
        self._conn.commit()

    def get_aggregates(self, run_id: int) -> "models.MarketAggregates | None":
        with self._conn.cursor() as cur:
            cur.execute(
                f"SELECT aggregates FROM {self._schema}.scan_runs WHERE run_id=%s",
                (run_id,),
            )
            row = cur.fetchone()
        if not row or not row[0]:
            return None
        return models.MarketAggregates.model_validate(row[0])

    # get_pcr_history_row moved to _MarketDataMixin

    # stock_history_rollup, watchlist count, record health, heartbeat methods moved to _HealthMixin

    # ---- strike_gex_curve (JSONB on scan_runs) ----

    def set_strike_gex_curve(self, run_id: int, curve: list[dict]) -> None:
        """Persist the per-strike, per-expiry GEX curve as JSONB on the run row."""
        with self._conn.cursor() as cur:
            cur.execute(
                f"UPDATE {self._schema}.scan_runs SET strike_gex_curve=%s WHERE run_id=%s",
                (Jsonb(curve), run_id),
            )
        self._conn.commit()

    def get_strike_gex_curve(self, run_id: int) -> list[dict]:
        with self._conn.cursor() as cur:
            cur.execute(
                f"SELECT strike_gex_curve FROM {self._schema}.scan_runs WHERE run_id=%s",
                (run_id,),
            )
            row = cur.fetchone()
        return row[0] if row and row[0] else []

    # get_job moved to _JobsMixin

    # ---- Volatility Tab v2 helpers (spec 2026-05-13) ----
