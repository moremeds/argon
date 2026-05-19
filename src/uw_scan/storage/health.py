"""Health observability: per-table record coverage, watchlist count,
worker heartbeats, stock history rollup.

list_record_health auto-discovers all uw_scan tables and reports how many
rows landed in the rolling window for each table that looks tickered (has
both a timestamp and ticker column). The 3 _RECORD_HEALTH_* constants
filter what counts as 'tickered' and which tables to skip."""

from __future__ import annotations

import math
from collections.abc import Iterable
from datetime import datetime

import psycopg
from psycopg import sql as psql

from .rows import RecordHealthRow

_RECORD_HEALTH_TIMESTAMP_COLUMNS = ("updated_at", "inserted_at")
_RECORD_HEALTH_TICKER_COLUMNS = ("ticker", "underlying_symbol")
_RECORD_HEALTH_EXCLUDED_TABLES = {
    # Request logs and orchestration tables are covered by provider usage /
    # scheduler health, not per-ticker persisted data coverage.
    "external_api_requests",
    "scan_results",
    "scan_universe",
    # Not watchlist-scoped periodic UW source tables.
    "index_ohlc_daily",
    "opportunity_scores",
    "structure_ideas",
    # Derived/backfill tables that do not update for every ticker each RTH window.
    "iv_smile_snapshots",
    "oi_by_expiry",
    "option_surface_snapshots",
    "stock_analytics_daily",
    "vrp_daily",
    # Cockpit-only tables — populated for the 4 index tickers (SPX/SPY/QQQ/IWM)
    # by `cockpit_daily_snapshot`, never for the full watchlist. Including
    # them in watchlist coverage always reads "4/102 ALERT" which is false.
    "charm_signals",
    "vanna_signals",
    "matrix_state_snapshots",
    "vrp_30d_settlements",
    # Structurally sparse: only tickers that pass scan gates get a context
    # flag row. Even at full coverage this caps around 50-60% of the
    # watchlist — a watchlist-wide threshold will never apply.
    "signal_context_flags",
}

# Watchlist-wide tables populated once per day (nightly vol rollup at
# 18:00 ET; daily skew + oi_by_strike snapshots). An 8h sliding window
# will always fail them — they need a 24h+ window to count as fresh.
_RECORD_HEALTH_DAILY_TABLES = {
    # nightly_vol_analytics_rollup
    "iv_rank_history",
    "realized_volatility_history",
    "volatility_stats_history",
    # daily snapshots
    "risk_reversal_skew_history",
    "oi_by_strike",
}


class _HealthMixin:
    _conn: psycopg.Connection
    _schema: str

    # ---- stock history rollup (for Market Structure history table) ----
    def fetch_stock_history_rollup(self, ticker: str, limit: int = 30) -> list[dict]:
        """One row per trading day, latest successful scan_run on that date.

        Joins to daily_ohlc for end-of-day spot. Returns dicts shaped for
        api.routers.stock to wrap in StockHistoryRow models.
        """
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                WITH daily_runs AS (
                    SELECT DISTINCT ON (started_at::date)
                        started_at::date AS market_date,
                        strike_gex_curve,
                        aggregates
                    FROM {self._schema}.scan_runs
                    WHERE ticker = %s
                      AND status = 'ok'
                      AND strike_gex_curve IS NOT NULL
                    ORDER BY started_at::date DESC, started_at DESC
                )
                SELECT
                    r.market_date,
                    d.close AS spot,
                    r.aggregates->>'iv30d' AS iv30d,
                    r.aggregates->>'pcr_vol' AS pcr_vol,
                    r.strike_gex_curve
                FROM daily_runs r
                LEFT JOIN {self._schema}.daily_ohlc d
                  ON d.ticker = %s AND d.date = r.market_date
                ORDER BY r.market_date DESC
                LIMIT %s
                """,
                (ticker, ticker, limit),
            )
            return [
                {
                    "market_date": row[0],
                    "spot": row[1],
                    "iv30d": row[2],
                    "pcr_vol": row[3],
                    "strike_gex_curve": row[4],
                }
                for row in cur.fetchall()
            ]

    # ---- watchlist count (for HealthPanel) ----
    def count_active_watchlist(self) -> int:
        with self._conn.cursor() as cur:
            cur.execute(
                f"SELECT COUNT(*) FROM {self._schema}.watchlist WHERE removed_at IS NULL"
            )
            row = cur.fetchone()
        return int(row[0]) if row else 0

    def _discover_record_health_rules(self) -> dict[str, tuple[str, str, int]]:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_name, array_agg(column_name::text ORDER BY ordinal_position)
                FROM information_schema.columns
                WHERE table_schema = %s
                GROUP BY table_name
                ORDER BY table_name
                """,
                (self._schema,),
            )
            discovered: dict[str, tuple[str, str, int]] = {}
            for table, column_list in cur.fetchall():
                table_name = str(table)
                if table_name in _RECORD_HEALTH_EXCLUDED_TABLES:
                    continue
                columns = set(column_list or [])
                timestamp_col = next(
                    (
                        column
                        for column in _RECORD_HEALTH_TIMESTAMP_COLUMNS
                        if column in columns
                    ),
                    None,
                )
                ticker_col = next(
                    (
                        column
                        for column in _RECORD_HEALTH_TICKER_COLUMNS
                        if column in columns
                    ),
                    None,
                )
                if timestamp_col is not None and ticker_col is not None:
                    discovered[table_name] = (timestamp_col, ticker_col, 1)
            return discovered

    def list_record_health(
        self,
        *,
        since: datetime,
        expected_tickers: int,
        min_coverage: float = 0.9,
        tables: Iterable[str] | None = None,
        daily_since: datetime | None = None,
    ) -> list[RecordHealthRow]:
        rules = self._discover_record_health_rules()
        selected = list(tables) if tables is not None else list(rules)
        unknown = sorted(set(selected) - set(rules))
        if unknown:
            raise ValueError(f"unknown record health table(s): {', '.join(unknown)}")

        expected_min_tickers = (
            0 if expected_tickers <= 0 else math.ceil(expected_tickers * min_coverage)
        )
        rows: list[RecordHealthRow] = []
        with self._conn.cursor() as cur:
            for table in selected:
                timestamp_col, ticker_col, min_rows_per_ticker = rules[table]
                # Tables populated by once-per-day jobs (cockpit, vol rollup)
                # cannot satisfy an 8h sliding window — they need a 24h+ one.
                effective_since = (
                    daily_since
                    if (
                        daily_since is not None and table in _RECORD_HEALTH_DAILY_TABLES
                    )
                    else since
                )
                cur.execute(
                    psql.SQL(
                        """
                        SELECT
                            COUNT(*)::int AS actual_rows,
                            COUNT(DISTINCT {ticker_col})::int AS actual_tickers,
                            MAX({timestamp_col}) AS latest_at
                        FROM {schema}.{table}
                        WHERE {timestamp_col} >= %s
                        """
                    ).format(
                        schema=psql.Identifier(self._schema),
                        table=psql.Identifier(table),
                        timestamp_col=psql.Identifier(timestamp_col),
                        ticker_col=psql.Identifier(ticker_col),
                    ),
                    (effective_since,),
                )
                actual_rows, actual_tickers, latest_at = cur.fetchone() or (0, 0, None)
                expected_min_rows = expected_min_tickers * min_rows_per_ticker
                ok = (
                    int(actual_tickers or 0) >= expected_min_tickers
                    and int(actual_rows or 0) >= expected_min_rows
                )
                rows.append(
                    RecordHealthRow(
                        table=table,
                        window_start=effective_since,
                        expected_tickers=expected_tickers,
                        expected_min_tickers=expected_min_tickers,
                        actual_tickers=int(actual_tickers or 0),
                        expected_min_rows=expected_min_rows,
                        actual_rows=int(actual_rows or 0),
                        latest_at=latest_at,
                        ok=ok,
                    )
                )
        return rows

    # ---- worker_heartbeat ----
    def upsert_heartbeat(self, job_name: str) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {self._schema}.worker_heartbeat (job_name, last_beat_at)
                VALUES (%s, now())
                ON CONFLICT (job_name) DO UPDATE SET last_beat_at = now()
                """,
                (job_name,),
            )
        self._conn.commit()

    def get_heartbeat(self, job_name: str) -> datetime | None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"SELECT last_beat_at FROM {self._schema}.worker_heartbeat WHERE job_name=%s",
                (job_name,),
            )
            row = cur.fetchone()
        return row[0] if row else None

    def get_heartbeats(self, job_names: Iterable[str]) -> dict[str, datetime]:
        names = list(dict.fromkeys(job_names))
        if not names:
            return {}
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT job_name, last_beat_at
                FROM {self._schema}.worker_heartbeat
                WHERE job_name = ANY(%s)
                """,
                (names,),
            )
            return {row[0]: row[1] for row in cur.fetchall()}

    def get_latest_heartbeat(self) -> tuple[str, datetime] | None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT job_name, last_beat_at
                FROM {self._schema}.worker_heartbeat
                ORDER BY last_beat_at DESC
                LIMIT 1
                """
            )
            row = cur.fetchone()
        return (str(row[0]), row[1]) if row else None
