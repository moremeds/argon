"""Persistence layer: thin wrapper around psycopg cursors.

One method per insert/select. No `**kwargs` splatting from arbitrary dicts.
"""

from __future__ import annotations

import logging
import math
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date as _date
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import psycopg
from psycopg import sql as psql
from psycopg.types.json import Jsonb

from .. import models


@dataclass(frozen=True)
class WatchlistRow:
    ticker: str
    sector: str
    notes: str | None
    pinned: bool
    sort_rank: int
    added_at: datetime
    removed_at: datetime | None


@dataclass(frozen=True)
class DailyOhlcRow:
    ticker: str
    date: _date
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal
    volume: int | None
    source: str
    fetched_at: datetime


@dataclass(frozen=True)
class IntradayQuoteRow:
    ticker: str
    price: Decimal
    quoted_at: datetime
    fetched_at: datetime


@dataclass(frozen=True)
class PcrHistoryRow:
    ticker: str
    snapshot_date: _date
    pcr_oi: Decimal | None
    pcr_vol: Decimal | None


@dataclass(frozen=True)
class JobRow:
    id: Any
    ticker: str
    status: str
    run_id: int | None
    error: str | None
    requested_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    claim_token: Any = None  # UUID, set on claim, gates mark_job_done/failed


@dataclass(frozen=True)
class RescanQueueSummaryRow:
    total: int
    queued: int
    running: int
    oldest_requested_at: datetime | None


@dataclass(frozen=True)
class ExternalApiUsageSummary:
    total_requests: int
    http_2xx: int
    http_3xx: int
    http_4xx: int
    http_5xx: int
    transport_errors: int
    latency_p95_ms: int | None
    uw_latest_daily_count: int | None
    uw_latest_daily_limit: int | None


@dataclass(frozen=True)
class ExternalApiBreakdownRow:
    key: str | None
    total_requests: int
    http_2xx: int
    http_3xx: int
    http_4xx: int
    http_5xx: int
    transport_errors: int
    latency_p95_ms: int | None


@dataclass(frozen=True)
class ThroughputSummaryRow:
    window_minutes: float
    requests_per_minute: float
    http_429: int
    avg_scan_duration_seconds: float | None
    queue_drain_rate_per_minute: float | None


@dataclass(frozen=True)
class ExternalApiRequestRow:
    request_id: int
    provider: str
    endpoint_key: str
    method: str
    path: str
    ticker: str | None
    params: dict[str, Any]
    status_code: int | None
    status_family: str
    request_started_at: datetime
    request_finished_at: datetime
    latency_ms: int
    attempt: int
    run_id: int | None
    job_name: str | None
    provider_request_id: str | None
    official_daily_count: int | None
    official_daily_limit: int | None
    official_minute_remaining: int | None
    official_minute_reset: str | None
    error_message: str | None


@dataclass(frozen=True)
class RecordHealthRow:
    table: str
    window_start: datetime
    expected_tickers: int
    expected_min_tickers: int
    actual_tickers: int
    expected_min_rows: int
    actual_rows: int
    latest_at: datetime | None
    ok: bool


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
}


class WatchlistCardRow:
    """Variable-shaped: 25+ fields, many nullable. Wraps a dict for forward-compat
    when the card schema grows. Use .from_db(row, cursor.description) to construct."""

    def __init__(self, data: dict):
        self._data = data

    def __getattr__(self, name: str):
        try:
            data = object.__getattribute__(self, "_data")
        except AttributeError as e:
            raise AttributeError(name) from e
        if name in data:
            return data[name]
        raise AttributeError(name)

    @classmethod
    def from_db(cls, row: tuple, description) -> "WatchlistCardRow":
        return cls({col.name: val for col, val in zip(description, row, strict=False)})

    def to_dict(self) -> dict:
        return dict(self._data)


logger = logging.getLogger(__name__)
_PROVIDER_DAY_TZ = ZoneInfo("America/New_York")
_REDACTED_PARAM_KEYS = {
    "apikey",
    "api_key",
    "authorization",
    "auth",
    "token",
}


def _d(value: Decimal | None) -> Any:
    """psycopg handles Decimal natively; keep this for symmetry with other casters."""
    return value


def provider_day_bounds(now: datetime | None = None) -> tuple[datetime, datetime]:
    current = now or datetime.now(tz=_PROVIDER_DAY_TZ)
    local = current.astimezone(_PROVIDER_DAY_TZ)
    reset = local.replace(hour=20, minute=0, second=0, microsecond=0)
    if local < reset:
        reset -= timedelta(days=1)
    return reset, reset + timedelta(days=1)


def status_family_for(status_code: int | None, *, transport_error: bool = False) -> str:
    if transport_error:
        return "transport_error"
    if status_code is None:
        return "transport_error"
    if 200 <= status_code <= 299:
        return "2xx"
    if 300 <= status_code <= 399:
        return "3xx"
    if 400 <= status_code <= 499:
        return "4xx"
    if 500 <= status_code <= 599:
        return "5xx"
    return "transport_error"


def redact_params(params: dict[str, object] | None) -> dict[str, object]:
    redacted: dict[str, object] = {}
    for key, value in (params or {}).items():
        if key.lower() in _REDACTED_PARAM_KEYS:
            continue
        if isinstance(value, str) and len(value) > 256:
            redacted[key] = value[:253] + "..."
        else:
            redacted[key] = value
    return redacted


def _nullable_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(round(float(value)))


def _nullable_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


class Repository:
    """Repository wraps a psycopg connection and exposes typed CRUD."""

    def __init__(self, conn: psycopg.Connection, schema: str = "uw_scan") -> None:
        self._conn = conn
        self._schema = schema

    @property
    def conn(self) -> psycopg.Connection:
        return self._conn

    # ------------------------------------------------------------------
    # scan_runs
    # ------------------------------------------------------------------
    def latest_run_id(self, ticker: str) -> int:
        """Return the highest full-scan run_id for `ticker`, or 0 if none.

        Excludes runs created by ``flow_data_refresh`` — that job populates
        ticker-keyed tables only (options_volume_daily, option_chain_per_strike)
        and its scan_runs row would otherwise shadow the actual full-scan run
        the report assembler needs for flow_alerts / oi_change_top / GEX /
        volatility data, which are all keyed by run_id.
        """
        with self._conn.cursor() as cur:
            cur.execute(
                f"SELECT run_id FROM {self._schema}.scan_runs "
                "WHERE ticker = %s "
                "  AND (notes IS DISTINCT FROM 'flow_data_refresh') "
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
    # api_request_audit + raw_payloads
    # ------------------------------------------------------------------
    def insert_audit_row(
        self,
        run_id: int,
        endpoint_slug: str,
        endpoint_path: str,
        params: dict[str, Any],
        status_code: int,
        started_at: datetime,
        finished_at: datetime,
        daily_req_count: int | None,
        minute_req_remaining: int | None,
        minute_req_reset: str | None,
        error_message: str | None = None,
    ) -> int:
        sql = (
            f"INSERT INTO {self._schema}.api_request_audit ("
            "run_id, endpoint_slug, endpoint_path, params_json, status_code, "
            "request_started_at, request_finished_at, daily_req_count, "
            "minute_req_remaining, minute_req_reset, error_message) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING audit_id"
        )
        with self._conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    run_id,
                    endpoint_slug,
                    endpoint_path,
                    Jsonb(params),
                    status_code,
                    started_at,
                    finished_at,
                    daily_req_count,
                    minute_req_remaining,
                    minute_req_reset,
                    error_message,
                ),
            )
            row = cur.fetchone()
        assert row is not None
        return int(row[0])

    def insert_raw_payload(self, audit_id: int, payload: dict | list) -> int:
        sql = (
            f"INSERT INTO {self._schema}.raw_payloads (audit_id, payload_jsonb) "
            "VALUES (%s, %s) RETURNING payload_id"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (audit_id, Jsonb(payload)))
            row = cur.fetchone()
        assert row is not None
        return int(row[0])

    # ------------------------------------------------------------------
    # external_api_requests
    # ------------------------------------------------------------------
    def insert_external_api_request(
        self,
        *,
        provider: str,
        endpoint_key: str,
        method: str,
        path_template: str | None = None,
        path: str,
        ticker: str | None = None,
        params: dict[str, Any] | None = None,
        status_code: int | None = None,
        status_family: str,
        started_at: datetime,
        finished_at: datetime,
        latency_ms: int,
        attempt: int = 0,
        run_id: int | None = None,
        job_name: str | None = None,
        provider_request_id: str | None = None,
        official_daily_count: int | None = None,
        official_daily_limit: int | None = None,
        official_minute_remaining: int | None = None,
        official_minute_reset: str | None = None,
        error_message: str | None = None,
    ) -> int:
        sql = (
            f"INSERT INTO {self._schema}.external_api_requests ("
            "provider, endpoint_key, method, path_template, path, ticker, "
            "params_json, status_code, status_family, request_started_at, "
            "request_finished_at, latency_ms, attempt, run_id, job_name, "
            "provider_request_id, official_daily_count, official_daily_limit, "
            "official_minute_remaining, official_minute_reset, error_message) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
            "%s, %s, %s, %s, %s, %s, %s) RETURNING request_id"
        )
        with self._conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    provider,
                    endpoint_key,
                    method,
                    path_template,
                    path,
                    ticker.upper() if ticker else None,
                    Jsonb(params or {}),
                    status_code,
                    status_family,
                    started_at,
                    finished_at,
                    latency_ms,
                    attempt,
                    run_id,
                    job_name,
                    provider_request_id,
                    official_daily_count,
                    official_daily_limit,
                    official_minute_remaining,
                    official_minute_reset,
                    error_message,
                ),
            )
            row = cur.fetchone()
        assert row is not None
        return int(row[0])

    def get_external_api_usage_summary(
        self, provider: str | None, start: datetime, end: datetime
    ) -> ExternalApiUsageSummary:
        provider_filter = None if provider in (None, "all") else provider
        sql = (
            "WITH scoped AS ("
            f"SELECT * FROM {self._schema}.external_api_requests "
            "WHERE request_started_at >= %s "
            "  AND request_started_at < %s "
            "  AND (%s::text IS NULL OR provider = %s)"
            "), latest_uw AS ("
            "SELECT official_daily_count, official_daily_limit "
            "FROM scoped "
            "WHERE provider = 'uw' "
            "  AND official_daily_count IS NOT NULL "
            "ORDER BY request_started_at DESC, request_id DESC "
            "LIMIT 1"
            ") "
            "SELECT "
            "COUNT(*)::int AS total_requests, "
            "COUNT(*) FILTER (WHERE status_family = '2xx')::int AS http_2xx, "
            "COUNT(*) FILTER (WHERE status_family = '3xx')::int AS http_3xx, "
            "COUNT(*) FILTER (WHERE status_family = '4xx')::int AS http_4xx, "
            "COUNT(*) FILTER (WHERE status_family = '5xx')::int AS http_5xx, "
            "COUNT(*) FILTER (WHERE status_family = 'transport_error')::int "
            "    AS transport_errors, "
            "percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) "
            "    AS latency_p95_ms, "
            "(SELECT official_daily_count FROM latest_uw) AS uw_latest_daily_count, "
            "(SELECT official_daily_limit FROM latest_uw) AS uw_latest_daily_limit "
            "FROM scoped"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (start, end, provider_filter, provider_filter))
            row = cur.fetchone()
        assert row is not None
        return ExternalApiUsageSummary(
            total_requests=int(row[0]),
            http_2xx=int(row[1]),
            http_3xx=int(row[2]),
            http_4xx=int(row[3]),
            http_5xx=int(row[4]),
            transport_errors=int(row[5]),
            latency_p95_ms=_nullable_int(row[6]),
            uw_latest_daily_count=row[7],
            uw_latest_daily_limit=row[8],
        )

    def get_throughput_summary(
        self, provider: str | None, start: datetime, end: datetime
    ) -> ThroughputSummaryRow:
        provider_filter = None if provider in (None, "all") else provider
        # scan_runs and jobs do not carry a provider column — both are UW-only
        # sources. When the caller asks about a non-UW provider, return None
        # for those fields rather than UW values mislabelled (review 2026-05-16, B2).
        is_uw_scoped = provider_filter is None or provider_filter == "uw"

        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                  count(*)::int AS total_requests,
                  count(*) FILTER (WHERE status_code = 429)::int AS http_429,
                  min(request_started_at) AS first_request_at
                FROM {self._schema}.external_api_requests
                WHERE request_started_at >= %s
                  AND request_started_at < %s
                  AND (%s::text IS NULL OR provider = %s)
                """,
                (start, end, provider_filter, provider_filter),
            )
            request_row = cur.fetchone()

            scan_avg: float | None = None
            scan_first: datetime | None = None
            if is_uw_scoped:
                cur.execute(
                    f"""
                    SELECT avg(extract(epoch FROM finished_at - started_at))
                         , min(started_at)
                    FROM {self._schema}.scan_runs
                    WHERE finished_at >= %s
                      AND finished_at < %s
                      AND finished_at IS NOT NULL
                      AND started_at IS NOT NULL
                      AND (notes IS DISTINCT FROM 'flow_data_refresh')
                    """,
                    (start, end),
                )
                scan_row = cur.fetchone()
                if scan_row is not None:
                    scan_avg = _nullable_float(scan_row[0])
                    scan_first = scan_row[1]

            queue_count: int | None = None
            queue_first: datetime | None = None
            if is_uw_scoped:
                cur.execute(
                    f"""
                    SELECT count(*)::int, min(requested_at)
                    FROM {self._schema}.jobs
                    WHERE finished_at >= %s
                      AND finished_at < %s
                      AND status IN ('done', 'failed')
                    """,
                    (start, end),
                )
                queue_row = cur.fetchone()
                if queue_row is not None:
                    queue_count = int(queue_row[0])
                    queue_first = queue_row[1]

        total_requests = int(request_row[0])
        active_starts = [request_row[2], scan_first, queue_first]
        first_activity = min(
            (ts for ts in active_starts if ts is not None), default=start
        )
        active_start = max(start, first_activity)
        active_window_minutes = max((end - active_start).total_seconds() / 60.0, 1 / 60)
        return ThroughputSummaryRow(
            window_minutes=active_window_minutes,
            requests_per_minute=total_requests / active_window_minutes,
            http_429=int(request_row[1]),
            avg_scan_duration_seconds=scan_avg,
            queue_drain_rate_per_minute=(
                queue_count / active_window_minutes if queue_count is not None else None
            ),
        )

    def list_external_api_endpoint_usage(
        self, provider: str | None, start: datetime, end: datetime
    ) -> list[ExternalApiBreakdownRow]:
        return self._list_external_api_breakdown(
            "endpoint_key", provider=provider, start=start, end=end
        )

    def list_external_api_ticker_usage(
        self, provider: str | None, start: datetime, end: datetime
    ) -> list[ExternalApiBreakdownRow]:
        return self._list_external_api_breakdown(
            "ticker", provider=provider, start=start, end=end
        )

    def _list_external_api_breakdown(
        self, column: str, *, provider: str | None, start: datetime, end: datetime
    ) -> list[ExternalApiBreakdownRow]:
        if column not in {"endpoint_key", "ticker"}:
            raise ValueError(f"unsupported external API breakdown: {column}")
        provider_filter = None if provider in (None, "all") else provider
        sql = (
            f"SELECT {column} AS key, "
            "COUNT(*)::int AS total_requests, "
            "COUNT(*) FILTER (WHERE status_family = '2xx')::int AS http_2xx, "
            "COUNT(*) FILTER (WHERE status_family = '3xx')::int AS http_3xx, "
            "COUNT(*) FILTER (WHERE status_family = '4xx')::int AS http_4xx, "
            "COUNT(*) FILTER (WHERE status_family = '5xx')::int AS http_5xx, "
            "COUNT(*) FILTER (WHERE status_family = 'transport_error')::int "
            "    AS transport_errors, "
            "percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) "
            "    AS latency_p95_ms "
            f"FROM {self._schema}.external_api_requests "
            "WHERE request_started_at >= %s "
            "  AND request_started_at < %s "
            "  AND (%s::text IS NULL OR provider = %s) "
            f"GROUP BY {column} "
            "ORDER BY total_requests DESC, key ASC NULLS LAST"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (start, end, provider_filter, provider_filter))
            rows = cur.fetchall()
        return [
            ExternalApiBreakdownRow(
                key=row[0],
                total_requests=int(row[1]),
                http_2xx=int(row[2]),
                http_3xx=int(row[3]),
                http_4xx=int(row[4]),
                http_5xx=int(row[5]),
                transport_errors=int(row[6]),
                latency_p95_ms=_nullable_int(row[7]),
            )
            for row in rows
        ]

    def list_external_api_requests(
        self,
        *,
        provider: str | None,
        start: datetime,
        end: datetime,
        ticker: str | None = None,
        status_family: str | None = None,
        limit: int = 100,
    ) -> list[ExternalApiRequestRow]:
        provider_filter = None if provider in (None, "all") else provider
        ticker_filter = ticker.upper() if ticker else None
        bounded_limit = max(1, min(limit, 500))
        sql = (
            "SELECT request_id, provider, endpoint_key, method, path, ticker, "
            "params_json, status_code, status_family, request_started_at, "
            "request_finished_at, latency_ms, attempt, run_id, job_name, "
            "provider_request_id, official_daily_count, official_daily_limit, "
            "official_minute_remaining, official_minute_reset, error_message "
            f"FROM {self._schema}.external_api_requests "
            "WHERE request_started_at >= %s "
            "  AND request_started_at < %s "
            "  AND (%s::text IS NULL OR provider = %s) "
            "  AND (%s::text IS NULL OR ticker = %s) "
            "  AND (%s::text IS NULL OR status_family = %s) "
            "ORDER BY request_started_at DESC, request_id DESC "
            "LIMIT %s"
        )
        with self._conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    start,
                    end,
                    provider_filter,
                    provider_filter,
                    ticker_filter,
                    ticker_filter,
                    status_family,
                    status_family,
                    bounded_limit,
                ),
            )
            rows = cur.fetchall()
        return [
            ExternalApiRequestRow(
                request_id=int(row[0]),
                provider=row[1],
                endpoint_key=row[2],
                method=row[3],
                path=row[4],
                ticker=row[5],
                params=dict(row[6]),
                status_code=row[7],
                status_family=row[8],
                request_started_at=row[9],
                request_finished_at=row[10],
                latency_ms=int(row[11]),
                attempt=int(row[12]),
                run_id=row[13],
                job_name=row[14],
                provider_request_id=row[15],
                official_daily_count=row[16],
                official_daily_limit=row[17],
                official_minute_remaining=row[18],
                official_minute_reset=row[19],
                error_message=row[20],
            )
            for row in rows
        ]

    # ------------------------------------------------------------------
    # flow_events
    # ------------------------------------------------------------------
    def insert_flow_events(
        self, run_id: int, ticker: str, alerts: Iterable[models.FlowAlert]
    ) -> int:
        rows = list(alerts)
        if not rows:
            return 0
        sql = (
            f"INSERT INTO {self._schema}.flow_events ("
            "run_id, alert_id, ticker, option_chain, expiry, strike, option_type, "
            "price, underlying_price, total_size, total_premium, "
            "total_ask_side_prem, total_bid_side_prem, volume, open_interest, "
            "volume_oi_ratio, has_sweep, has_floor, has_multileg, "
            "all_opening_trades, iv_start, iv_end, alert_rule, rule_id, sector, "
            "issue_type, next_earnings_date, created_at) VALUES ("
            "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
            "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (run_id, alert_id) DO NOTHING"
        )
        with self._conn.cursor() as cur:
            for r in rows:
                cur.execute(
                    sql,
                    (
                        run_id,
                        r.id,
                        r.ticker,
                        r.option_chain,
                        r.expiry,
                        r.strike,
                        r.type,
                        r.price,
                        r.underlying_price,
                        r.total_size,
                        r.total_premium,
                        r.total_ask_side_prem,
                        r.total_bid_side_prem,
                        r.volume,
                        r.open_interest,
                        r.volume_oi_ratio,
                        r.has_sweep,
                        r.has_floor,
                        r.has_multileg,
                        r.all_opening_trades,
                        r.iv_start,
                        r.iv_end,
                        r.alert_rule,
                        r.rule_id,
                        r.sector,
                        r.issue_type,
                        r.next_earnings_date,
                        r.created_at,
                    ),
                )
        return len(rows)

    def upsert_flow_alerts_daily_rollup(
        self,
        *,
        run_id: int,
        ticker: str,
        alerts: Iterable[models.FlowAlert],
        alert_limit: int,
        trade_date: _date | None = None,
    ) -> None:
        rows = list(alerts)
        if trade_date is None:
            trade_date = self._flow_alert_trade_date(rows)

        bull_premium = Decimal("0")
        bear_premium = Decimal("0")
        ask_side_premium = Decimal("0")
        bid_side_premium = Decimal("0")
        total_premium = Decimal("0")
        rules: Counter[str] = Counter()

        for row in rows:
            premium = row.total_premium or Decimal("0")
            total_premium += premium
            opt_type = (row.type or "").lower()
            if opt_type == "call":
                bull_premium += premium
            elif opt_type == "put":
                bear_premium += premium
            ask_side_premium += row.total_ask_side_prem or Decimal("0")
            bid_side_premium += row.total_bid_side_prem or Decimal("0")
            if row.alert_rule:
                rules[row.alert_rule] += 1

        top_alert_rule = rules.most_common(1)[0][0] if rules else None

        sql = (
            f"INSERT INTO {self._schema}.flow_alerts_daily_rollup ("
            "ticker, trade_date, run_id, alert_count, alert_count_is_limited, "
            "total_premium, bull_premium, bear_premium, ask_side_premium, "
            "bid_side_premium, top_alert_rule) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (ticker, trade_date) DO UPDATE SET "
            "run_id=EXCLUDED.run_id, alert_count=EXCLUDED.alert_count, "
            "alert_count_is_limited=EXCLUDED.alert_count_is_limited, "
            "total_premium=EXCLUDED.total_premium, "
            "bull_premium=EXCLUDED.bull_premium, "
            "bear_premium=EXCLUDED.bear_premium, "
            "ask_side_premium=EXCLUDED.ask_side_premium, "
            "bid_side_premium=EXCLUDED.bid_side_premium, "
            "top_alert_rule=EXCLUDED.top_alert_rule, updated_at=now()"
        )
        with self._conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    ticker.upper(),
                    trade_date,
                    run_id,
                    len(rows),
                    len(rows) >= alert_limit,
                    total_premium,
                    bull_premium,
                    bear_premium,
                    ask_side_premium,
                    bid_side_premium,
                    top_alert_rule,
                ),
            )

    def _flow_alert_trade_date(self, rows: list[models.FlowAlert]) -> _date:
        market_tz = ZoneInfo("America/New_York")
        for row in rows:
            if row.created_at is None:
                continue
            created_at = row.created_at
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=market_tz)
            return created_at.astimezone(market_tz).date()
        return datetime.now(market_tz).date()

    # ------------------------------------------------------------------
    # Time-series history (UPSERT by (ticker, market_date))
    # ------------------------------------------------------------------
    def upsert_iv_rank_rows(self, ticker: str, rows: Iterable[models.IvRankRow]) -> int:
        rows = list(rows)
        if not rows:
            return 0
        sql = (
            f"INSERT INTO {self._schema}.iv_rank_history "
            "(ticker, market_date, close, volatility, iv_rank_1y, updated_at_src) "
            "VALUES (%s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (ticker, market_date) DO UPDATE SET "
            "close=EXCLUDED.close, volatility=EXCLUDED.volatility, "
            "iv_rank_1y=EXCLUDED.iv_rank_1y, updated_at_src=EXCLUDED.updated_at_src"
        )
        with self._conn.cursor() as cur:
            for r in rows:
                cur.execute(
                    sql,
                    (ticker, r.date, r.close, r.volatility, r.iv_rank_1y, r.updated_at),
                )
        return len(rows)

    def upsert_volatility_stats_rows(self, rows: Iterable[models.VolStatsRow]) -> int:
        rows = list(rows)
        if not rows:
            return 0
        sql = (
            f"INSERT INTO {self._schema}.volatility_stats_history "
            "(ticker, market_date, iv, iv_low, iv_high, iv_rank, rv, rv_low, rv_high) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (ticker, market_date) DO UPDATE SET "
            "iv=EXCLUDED.iv, iv_low=EXCLUDED.iv_low, iv_high=EXCLUDED.iv_high, "
            "iv_rank=EXCLUDED.iv_rank, rv=EXCLUDED.rv, rv_low=EXCLUDED.rv_low, "
            "rv_high=EXCLUDED.rv_high"
        )
        with self._conn.cursor() as cur:
            for r in rows:
                cur.execute(
                    sql,
                    (
                        r.ticker,
                        r.date,
                        r.iv,
                        r.iv_low,
                        r.iv_high,
                        r.iv_rank,
                        r.rv,
                        r.rv_low,
                        r.rv_high,
                    ),
                )
        return len(rows)

    def upsert_realized_vol_rows(
        self, ticker: str, rows: Iterable[models.RealizedVolRow]
    ) -> int:
        rows = list(rows)
        if not rows:
            return 0
        sql = (
            f"INSERT INTO {self._schema}.realized_volatility_history "
            "(ticker, market_date, price, implied_volatility, realized_volatility, "
            "unshifted_rv_date) VALUES (%s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (ticker, market_date) DO UPDATE SET "
            "price=EXCLUDED.price, implied_volatility=EXCLUDED.implied_volatility, "
            "realized_volatility=EXCLUDED.realized_volatility, "
            "unshifted_rv_date=EXCLUDED.unshifted_rv_date"
        )
        with self._conn.cursor() as cur:
            for r in rows:
                cur.execute(
                    sql,
                    (
                        ticker,
                        r.date,
                        r.price,
                        r.implied_volatility,
                        r.realized_volatility,
                        r.unshifted_rv_date,
                    ),
                )
        return len(rows)

    def upsert_skew_rows(self, ticker: str, rows: Iterable[models.SkewRow]) -> int:
        rows = list(rows)
        if not rows:
            return 0
        sql = (
            f"INSERT INTO {self._schema}.risk_reversal_skew_history "
            "(ticker, market_date, delta, expiry, risk_reversal) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (ticker, market_date, delta, expiry) DO UPDATE SET "
            "risk_reversal=EXCLUDED.risk_reversal"
        )
        with self._conn.cursor() as cur:
            for r in rows:
                cur.execute(
                    sql,
                    (ticker, r.date, r.delta, r.expiry, r.risk_reversal),
                )
        return len(rows)

    # ------------------------------------------------------------------
    # Run-keyed inserts
    # ------------------------------------------------------------------
    def insert_iv_term_rows(
        self, run_id: int, rows: Iterable[models.TermStructureRow]
    ) -> int:
        rows = list(rows)
        if not rows:
            return 0
        sql = (
            f"INSERT INTO {self._schema}.iv_term_snapshots "
            "(run_id, ticker, market_date, expiry, dte, volatility, "
            "implied_move, implied_move_perc) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (run_id, ticker, expiry) DO NOTHING"
        )
        with self._conn.cursor() as cur:
            for r in rows:
                cur.execute(
                    sql,
                    (
                        run_id,
                        r.ticker,
                        r.date,
                        r.expiry,
                        r.dte,
                        r.volatility,
                        r.implied_move,
                        r.implied_move_perc,
                    ),
                )
        return len(rows)

    def insert_interpolated_iv_rows(
        self, run_id: int, ticker: str, rows: Iterable[models.InterpolatedIvRow]
    ) -> int:
        rows = list(rows)
        if not rows:
            return 0
        sql = (
            f"INSERT INTO {self._schema}.interpolated_iv_snapshots "
            "(run_id, ticker, market_date, days, percentile, volatility, implied_move_perc) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (run_id, ticker, days) DO NOTHING"
        )
        with self._conn.cursor() as cur:
            for r in rows:
                cur.execute(
                    sql,
                    (
                        run_id,
                        ticker,
                        r.date,
                        r.days,
                        r.percentile,
                        r.volatility,
                        r.implied_move_perc,
                    ),
                )
        return len(rows)

    def insert_greek_exposure_rows(
        self, run_id: int, ticker: str, rows: Iterable[models.GreekExposureRow]
    ) -> int:
        rows = list(rows)
        if not rows:
            return 0
        sql = (
            f"INSERT INTO {self._schema}.exposures_by_expiry_strike "
            "(run_id, ticker, market_date, expiry, strike, dte, "
            "call_delta, put_delta, call_gex, put_gex, call_vanna, put_vanna, "
            "call_charm, put_charm) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (run_id, ticker, expiry, strike) DO NOTHING"
        )
        with self._conn.cursor() as cur:
            for r in rows:
                cur.execute(
                    sql,
                    (
                        run_id,
                        ticker,
                        r.date,
                        r.expiry,
                        r.strike,
                        r.dte,
                        r.call_delta,
                        r.put_delta,
                        r.call_gex,
                        r.put_gex,
                        r.call_vanna,
                        r.put_vanna,
                        r.call_charm,
                        r.put_charm,
                    ),
                )
        return len(rows)

    def insert_greeks_rows(
        self, run_id: int, ticker: str, rows: Iterable[models.GreeksRow]
    ) -> int:
        rows = list(rows)
        if not rows:
            return 0
        sql = (
            f"INSERT INTO {self._schema}.greeks_by_expiry_strike "
            "(run_id, ticker, market_date, expiry, strike, "
            "call_delta, put_delta, call_gamma, put_gamma, call_vega, put_vega, "
            "call_theta, put_theta, call_rho, put_rho, "
            "call_vanna, put_vanna, call_charm, put_charm, "
            "call_volatility, put_volatility, "
            "call_option_symbol, put_option_symbol) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
            "%s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (run_id, ticker, expiry, strike) DO NOTHING"
        )
        with self._conn.cursor() as cur:
            for r in rows:
                cur.execute(
                    sql,
                    (
                        run_id,
                        ticker,
                        r.date,
                        r.expiry,
                        r.strike,
                        r.call_delta,
                        r.put_delta,
                        r.call_gamma,
                        r.put_gamma,
                        r.call_vega,
                        r.put_vega,
                        r.call_theta,
                        r.put_theta,
                        r.call_rho,
                        r.put_rho,
                        r.call_vanna,
                        r.put_vanna,
                        r.call_charm,
                        r.put_charm,
                        r.call_volatility,
                        r.put_volatility,
                        r.call_option_symbol,
                        r.put_option_symbol,
                    ),
                )
        return len(rows)

    def upsert_oi_per_strike_rows(
        self, ticker: str, rows: Iterable[models.OiPerStrikeRow]
    ) -> int:
        rows = list(rows)
        if not rows:
            return 0
        sql = (
            f"INSERT INTO {self._schema}.oi_by_strike "
            "(ticker, market_date, strike, call_oi, put_oi) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (ticker, market_date, strike) DO UPDATE SET "
            "call_oi=EXCLUDED.call_oi, put_oi=EXCLUDED.put_oi"
        )
        with self._conn.cursor() as cur:
            for r in rows:
                cur.execute(
                    sql,
                    (ticker, r.date, r.strike, r.call_oi, r.put_oi),
                )
        return len(rows)

    def upsert_options_volume_daily(
        self, ticker: str, rows: Iterable[models.OptionsDailyRow]
    ) -> int:
        rows = list(rows)
        if not rows:
            return 0
        sql = (
            f"INSERT INTO {self._schema}.options_volume_daily "
            "(ticker, trade_date, call_volume, put_volume, "
            " call_volume_ask_side, call_volume_bid_side, "
            " put_volume_ask_side, put_volume_bid_side, "
            " call_premium, put_premium, net_call_premium, net_put_premium, "
            " bullish_premium, bearish_premium, "
            " call_open_interest, put_open_interest, "
            " avg_3_day_call_volume, avg_3_day_put_volume, "
            " avg_7_day_call_volume, avg_7_day_put_volume, "
            " avg_30_day_call_volume, avg_30_day_put_volume) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
            "        %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (ticker, trade_date) DO UPDATE SET "
            "call_volume=EXCLUDED.call_volume, put_volume=EXCLUDED.put_volume, "
            "call_volume_ask_side=EXCLUDED.call_volume_ask_side, "
            "call_volume_bid_side=EXCLUDED.call_volume_bid_side, "
            "put_volume_ask_side=EXCLUDED.put_volume_ask_side, "
            "put_volume_bid_side=EXCLUDED.put_volume_bid_side, "
            "call_premium=EXCLUDED.call_premium, put_premium=EXCLUDED.put_premium, "
            "net_call_premium=EXCLUDED.net_call_premium, "
            "net_put_premium=EXCLUDED.net_put_premium, "
            "bullish_premium=EXCLUDED.bullish_premium, "
            "bearish_premium=EXCLUDED.bearish_premium, "
            "call_open_interest=EXCLUDED.call_open_interest, "
            "put_open_interest=EXCLUDED.put_open_interest, "
            "avg_3_day_call_volume=EXCLUDED.avg_3_day_call_volume, "
            "avg_3_day_put_volume=EXCLUDED.avg_3_day_put_volume, "
            "avg_7_day_call_volume=EXCLUDED.avg_7_day_call_volume, "
            "avg_7_day_put_volume=EXCLUDED.avg_7_day_put_volume, "
            "avg_30_day_call_volume=EXCLUDED.avg_30_day_call_volume, "
            "avg_30_day_put_volume=EXCLUDED.avg_30_day_put_volume"
        )
        with self._conn.cursor() as cur:
            for r in rows:
                cur.execute(
                    sql,
                    (
                        ticker,
                        r.date,
                        r.call_volume,
                        r.put_volume,
                        r.call_volume_ask_side,
                        r.call_volume_bid_side,
                        r.put_volume_ask_side,
                        r.put_volume_bid_side,
                        r.call_premium,
                        r.put_premium,
                        r.net_call_premium,
                        r.net_put_premium,
                        r.bullish_premium,
                        r.bearish_premium,
                        r.call_open_interest,
                        r.put_open_interest,
                        r.avg_3_day_call_volume,
                        r.avg_3_day_put_volume,
                        r.avg_7_day_call_volume,
                        r.avg_7_day_put_volume,
                        r.avg_30_day_call_volume,
                        r.avg_30_day_put_volume,
                    ),
                )
        return len(rows)

    def upsert_option_chain_per_strike(
        self,
        ticker: str,
        snapshot_date: _date,
        rows: Iterable[models.OptionChainPerStrikeRow],
    ) -> int:
        rows = list(rows)
        if not rows:
            return 0
        sql = (
            f"INSERT INTO {self._schema}.option_chain_per_strike "
            "(ticker, snapshot_date, expiry, strike, "
            " call_volume, put_volume, call_oi, put_oi) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (ticker, snapshot_date, expiry, strike) DO UPDATE SET "
            "call_volume=EXCLUDED.call_volume, put_volume=EXCLUDED.put_volume, "
            "call_oi=EXCLUDED.call_oi, put_oi=EXCLUDED.put_oi"
        )
        with self._conn.cursor() as cur:
            for r in rows:
                cur.execute(
                    sql,
                    (
                        ticker,
                        snapshot_date,
                        r.expiry,
                        r.strike,
                        r.call_volume,
                        r.put_volume,
                        r.call_oi,
                        r.put_oi,
                    ),
                )
        return len(rows)

    def delete_option_chain_per_strike(self, ticker: str, snapshot_date: _date) -> int:
        """Delete same-day rows before re-upserting a refreshed snapshot.

        Without this, a shrinking chain (fewer active strikes than last run)
        would leave stale rows in place since UPSERT only touches the keys
        present in the new batch.
        """

        with self._conn.cursor() as cur:
            cur.execute(
                f"DELETE FROM {self._schema}.option_chain_per_strike "
                f"WHERE ticker = %s AND snapshot_date = %s",
                (ticker, snapshot_date),
            )
            return cur.rowcount or 0

    def get_options_timeline(
        self, ticker: str, lookback_days: int = 180
    ) -> list[models.OptionsDailyRow]:
        sql = (
            f"SELECT trade_date AS date, call_volume, put_volume, "
            f"call_volume_ask_side, call_volume_bid_side, "
            f"put_volume_ask_side, put_volume_bid_side, "
            f"call_premium, put_premium, net_call_premium, net_put_premium, "
            f"bullish_premium, bearish_premium, "
            f"call_open_interest, put_open_interest, "
            f"avg_3_day_call_volume, avg_3_day_put_volume, "
            f"avg_7_day_call_volume, avg_7_day_put_volume, "
            f"avg_30_day_call_volume, avg_30_day_put_volume "
            f"FROM {self._schema}.options_volume_daily "
            f"WHERE ticker = %s AND trade_date >= (CURRENT_DATE - %s::int) "
            f"ORDER BY trade_date ASC"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker, lookback_days))
            cols = [c.name for c in cur.description]
            return [
                models.OptionsDailyRow(**dict(zip(cols, row, strict=True)))
                for row in cur.fetchall()
            ]

    def get_option_chain_per_strike(
        self, ticker: str
    ) -> list[models.OptionChainPerStrikeRow]:
        sql = (
            f"SELECT expiry, strike, call_volume, put_volume, call_oi, put_oi "
            f"FROM {self._schema}.option_chain_per_strike "
            f"WHERE ticker = %s AND snapshot_date = ("
            f"  SELECT MAX(snapshot_date) FROM {self._schema}.option_chain_per_strike "
            f"  WHERE ticker = %s) "
            f"ORDER BY expiry, strike"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker, ticker))
            cols = [c.name for c in cur.description]
            return [
                models.OptionChainPerStrikeRow(**dict(zip(cols, row, strict=True)))
                for row in cur.fetchall()
            ]

    def insert_oi_change_rows(
        self, run_id: int, rows: Iterable[models.OiChangeRow]
    ) -> int:
        rows = list(rows)
        if not rows:
            return 0
        sql = (
            f"INSERT INTO {self._schema}.oi_change_events "
            "(run_id, underlying_symbol, option_symbol, curr_date, last_date, "
            " curr_oi, last_oi, oi_diff_plain, oi_change, volume, trades, "
            " avg_price, last_fill, days_of_oi_increases, days_of_vol_greater_than_oi, "
            " percentage_of_total, rnk, "
            " prev_ask_volume, prev_bid_volume, prev_mid_volume, prev_neutral_volume, "
            " prev_multi_leg_volume, prev_stock_multi_leg_volume, "
            " prev_total_premium, last_ask, last_bid) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
            "        %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (run_id, option_symbol) DO NOTHING"
        )
        with self._conn.cursor() as cur:
            for r in rows:
                cur.execute(
                    sql,
                    (
                        run_id,
                        r.underlying_symbol,
                        r.option_symbol,
                        r.curr_date,
                        r.last_date,
                        r.curr_oi,
                        r.last_oi,
                        r.oi_diff_plain,
                        r.oi_change,
                        r.volume,
                        r.trades,
                        r.avg_price,
                        r.last_fill,
                        r.days_of_oi_increases,
                        r.days_of_vol_greater_than_oi,
                        r.percentage_of_total,
                        r.rnk,
                        r.prev_ask_volume,
                        r.prev_bid_volume,
                        r.prev_mid_volume,
                        r.prev_neutral_volume,
                        r.prev_multi_leg_volume,
                        r.prev_stock_multi_leg_volume,
                        r.prev_total_premium,
                        r.last_ask,
                        r.last_bid,
                    ),
                )
        return len(rows)

    def insert_max_pain_rows(
        self,
        run_id: int,
        ticker: str,
        market_date: Any,
        rows: Iterable[models.MaxPainRow],
    ) -> int:
        rows = list(rows)
        if not rows:
            return 0
        sql = (
            f"INSERT INTO {self._schema}.max_pain_by_expiry "
            "(run_id, ticker, market_date, expiry, max_pain, close, open, "
            "next_upper_strike, next_lower_strike) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (run_id, ticker, expiry) DO NOTHING"
        )
        with self._conn.cursor() as cur:
            for r in rows:
                cur.execute(
                    sql,
                    (
                        run_id,
                        ticker,
                        market_date,
                        r.expiry,
                        r.max_pain,
                        r.close,
                        r.open,
                        r.next_upper_strike,
                        r.next_lower_strike,
                    ),
                )
        return len(rows)

    def insert_option_contract_rows(
        self, run_id: int, ticker: str, rows: Iterable[models.OptionContractRow]
    ) -> int:
        rows = list(rows)
        if not rows:
            return 0
        sql = (
            f"INSERT INTO {self._schema}.option_contract_snapshots "
            "(run_id, ticker, option_symbol, last_price, nbbo_bid, nbbo_ask, "
            "implied_volatility, open_interest, prev_oi, volume, ask_volume, "
            "bid_volume, mid_volume, multi_leg_volume, stock_multi_leg_volume, "
            "floor_volume, sweep_volume, no_side_volume, "
            "avg_price, high_price, low_price, total_premium) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
            "%s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (run_id, option_symbol) DO NOTHING"
        )
        with self._conn.cursor() as cur:
            for r in rows:
                cur.execute(
                    sql,
                    (
                        run_id,
                        ticker,
                        r.option_symbol,
                        r.last_price,
                        r.nbbo_bid,
                        r.nbbo_ask,
                        r.implied_volatility,
                        r.open_interest,
                        r.prev_oi,
                        r.volume,
                        r.ask_volume,
                        r.bid_volume,
                        r.mid_volume,
                        r.multi_leg_volume,
                        r.stock_multi_leg_volume,
                        r.floor_volume,
                        r.sweep_volume,
                        r.no_side_volume,
                        r.avg_price,
                        r.high_price,
                        r.low_price,
                        r.total_premium,
                    ),
                )
        return len(rows)

    def insert_dark_pool_rows(
        self, run_id: int, rows: Iterable[models.DarkPoolPrint]
    ) -> int:
        rows = list(rows)
        if not rows:
            return 0
        sql = (
            f"INSERT INTO {self._schema}.dark_pool_events "
            "(run_id, ticker, tracking_id, executed_at, trf_executed_at, "
            "price, size, premium, nbbo_bid, nbbo_ask, "
            "nbbo_bid_quantity, nbbo_ask_quantity, market_center, "
            "sale_cond_codes, ext_hour_sold_codes, trade_code, trade_settlement, "
            "canceled) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (run_id, tracking_id) DO NOTHING"
        )
        with self._conn.cursor() as cur:
            for r in rows:
                cur.execute(
                    sql,
                    (
                        run_id,
                        r.ticker,
                        r.tracking_id,
                        r.executed_at,
                        r.trf_executed_at,
                        r.price,
                        r.size,
                        r.premium,
                        r.nbbo_bid,
                        r.nbbo_ask,
                        r.nbbo_bid_quantity,
                        r.nbbo_ask_quantity,
                        r.market_center,
                        r.sale_cond_codes,
                        r.ext_hour_sold_codes,
                        r.trade_code,
                        r.trade_settlement,
                        r.canceled,
                    ),
                )
        return len(rows)

    def insert_short_interest_snapshot(
        self, run_id: int, row: models.ShortDataRow
    ) -> int:
        sql = (
            f"INSERT INTO {self._schema}.short_interest_snapshots "
            "(run_id, ticker, name, snapshot_at, short_shares_available, "
            "fee_rate, rebate_rate) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (run_id) DO UPDATE SET "
            "snapshot_at=EXCLUDED.snapshot_at, "
            "short_shares_available=EXCLUDED.short_shares_available, "
            "fee_rate=EXCLUDED.fee_rate, rebate_rate=EXCLUDED.rebate_rate"
        )
        with self._conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    run_id,
                    row.symbol,
                    row.name,
                    row.timestamp,
                    row.short_shares_available,
                    row.fee_rate,
                    row.rebate_rate,
                ),
            )
        return 1

    # ------------------------------------------------------------------
    # opportunity_scores + structure_ideas
    # ------------------------------------------------------------------
    def insert_opportunity_score(
        self,
        run_id: int,
        ticker: str,
        score: Decimal,
        setup_types: list[str],
        direction: str | None,
        confirmations: list[str],
        warnings: list[str],
        notes: str,
    ) -> int:
        sql = (
            f"INSERT INTO {self._schema}.opportunity_scores "
            "(run_id, ticker, score, setup_types, direction, confirmations, "
            "warnings, notes) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING score_id"
        )
        with self._conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    run_id,
                    ticker,
                    score,
                    setup_types,
                    direction,
                    confirmations,
                    warnings,
                    notes,
                ),
            )
            row = cur.fetchone()
        assert row is not None
        return int(row[0])

    def insert_structure_idea(
        self,
        run_id: int,
        ticker: str,
        structure: str,
        legs: list[dict[str, Any]],
        rationale: str,
    ) -> int:
        sql = (
            f"INSERT INTO {self._schema}.structure_ideas "
            "(run_id, ticker, structure, legs_json, rationale) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING idea_id"
        )
        with self._conn.cursor() as cur:
            cur.execute(
                sql,
                (run_id, ticker, structure, Jsonb(legs), rationale),
            )
            row = cur.fetchone()
        assert row is not None
        return int(row[0])

    # ------------------------------------------------------------------
    # SELECT helpers — used by reports/single_stock.py
    # ------------------------------------------------------------------
    def fetch_flow_alerts_for_ticker(
        self, run_id: int, ticker: str
    ) -> list[dict[str, Any]]:
        sql = (
            f"SELECT alert_id, ticker, option_chain, expiry, strike, option_type, "
            "price, underlying_price, total_size, total_premium, "
            "total_ask_side_prem, total_bid_side_prem, volume, open_interest, "
            "volume_oi_ratio, has_sweep, has_floor, has_multileg, "
            "all_opening_trades, iv_start, iv_end, alert_rule, rule_id, sector, "
            "issue_type, next_earnings_date, created_at "
            f"FROM {self._schema}.flow_events "
            "WHERE run_id = %s AND ticker = %s "
            "ORDER BY total_premium DESC NULLS LAST"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (run_id, ticker.upper()))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def fetch_flow_alerts_daily_baseline(
        self, run_id: int, ticker: str, lookback_days: int = 30
    ) -> dict[str, Any] | None:
        sql = (
            "WITH current_rollup AS ("
            f"SELECT ticker, trade_date, alert_count, alert_count_is_limited, "
            "top_alert_rule "
            f"FROM {self._schema}.flow_alerts_daily_rollup "
            "WHERE run_id = %s AND ticker = %s "
            "ORDER BY trade_date DESC LIMIT 1"
            "), history AS ("
            f"SELECT h.alert_count "
            f"FROM {self._schema}.flow_alerts_daily_rollup h "
            "JOIN current_rollup c ON c.ticker = h.ticker "
            "WHERE h.trade_date < c.trade_date "
            "AND h.trade_date >= c.trade_date - (%s::int * INTERVAL '1 day')"
            ") "
            "SELECT c.alert_count, c.alert_count_is_limited, c.top_alert_rule, "
            "AVG(h.alert_count)::numeric AS avg_30d_alert_count, "
            "CASE WHEN AVG(h.alert_count) > 0 "
            "THEN ROUND(c.alert_count::numeric / AVG(h.alert_count)::numeric, 16) "
            "ELSE NULL END AS flow_count_vs_30d_avg, "
            "COUNT(h.alert_count)::int AS baseline_days "
            "FROM current_rollup c "
            "LEFT JOIN history h ON true "
            "GROUP BY c.alert_count, c.alert_count_is_limited, c.top_alert_rule"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (run_id, ticker.upper(), lookback_days))
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d.name for d in cur.description or []]
            return dict(zip(cols, row, strict=False))

    def fetch_iv_rank_latest(self, ticker: str) -> dict[str, Any] | None:
        sql = (
            f"SELECT market_date, close, volatility, iv_rank_1y, updated_at_src "
            f"FROM {self._schema}.iv_rank_history "
            "WHERE ticker = %s ORDER BY market_date DESC LIMIT 1"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker,))
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d.name for d in cur.description or []]
            return dict(zip(cols, row, strict=False))

    def fetch_volatility_stats_latest(self, ticker: str) -> dict[str, Any] | None:
        sql = (
            f"SELECT market_date, iv, iv_low, iv_high, iv_rank, rv, rv_low, rv_high "
            f"FROM {self._schema}.volatility_stats_history "
            "WHERE ticker = %s ORDER BY market_date DESC LIMIT 1"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker,))
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d.name for d in cur.description or []]
            return dict(zip(cols, row, strict=False))

    def fetch_realized_vol_latest(self, ticker: str) -> dict[str, Any] | None:
        sql = (
            f"SELECT market_date, price, implied_volatility, realized_volatility "
            f"FROM {self._schema}.realized_volatility_history "
            "WHERE ticker = %s ORDER BY market_date DESC LIMIT 1"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker,))
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d.name for d in cur.description or []]
            return dict(zip(cols, row, strict=False))

    def fetch_iv_term_rows(self, run_id: int, ticker: str) -> list[dict[str, Any]]:
        sql = (
            f"SELECT expiry, dte, volatility, implied_move, implied_move_perc "
            f"FROM {self._schema}.iv_term_snapshots "
            "WHERE run_id = %s AND ticker = %s ORDER BY expiry"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (run_id, ticker))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def fetch_interpolated_iv_30d(
        self, run_id: int, ticker: str
    ) -> dict[str, Any] | None:
        sql = (
            f"SELECT days, percentile, volatility, implied_move_perc "
            f"FROM {self._schema}.interpolated_iv_snapshots "
            "WHERE run_id = %s AND ticker = %s "
            "ORDER BY ABS(days - 30) ASC LIMIT 1"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (run_id, ticker))
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d.name for d in cur.description or []]
            return dict(zip(cols, row, strict=False))

    def fetch_skew_latest(self, ticker: str) -> dict[str, Any] | None:
        sql = (
            f"SELECT market_date, delta, expiry, risk_reversal "
            f"FROM {self._schema}.risk_reversal_skew_history "
            "WHERE ticker = %s AND delta = 25 "
            "ORDER BY market_date DESC LIMIT 1"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker,))
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d.name for d in cur.description or []]
            return dict(zip(cols, row, strict=False))

    def fetch_exposures_summary(
        self, run_id: int, ticker: str
    ) -> dict[str, Any] | None:
        sql = (
            f"SELECT "
            "SUM(call_gex) AS total_call_gex, "
            "SUM(put_gex) AS total_put_gex, "
            "SUM(call_delta) AS total_call_dex, "
            "SUM(put_delta) AS total_put_dex "
            f"FROM {self._schema}.exposures_by_expiry_strike "
            "WHERE run_id = %s AND ticker = %s"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (run_id, ticker))
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d.name for d in cur.description or []]
            return dict(zip(cols, row, strict=False))

    def fetch_top_oi_strikes(
        self, ticker: str, limit: int = 5
    ) -> tuple[list[Decimal], list[Decimal]]:
        sql = (
            f"SELECT strike, call_oi, put_oi FROM {self._schema}.oi_by_strike "
            "WHERE ticker = %s AND market_date = "
            f"(SELECT MAX(market_date) FROM {self._schema}.oi_by_strike WHERE ticker = %s)"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker, ticker))
            rows = cur.fetchall()
        calls = sorted(
            [r for r in rows if r[1] is not None],
            key=lambda r: r[1],
            reverse=True,
        )[:limit]
        puts = sorted(
            [r for r in rows if r[2] is not None],
            key=lambda r: r[2],
            reverse=True,
        )[:limit]
        return [Decimal(str(r[0])) for r in calls], [Decimal(str(r[0])) for r in puts]

    def fetch_oi_change_top(self, run_id: int, limit: int = 50) -> list[dict[str, Any]]:
        """Return a candidate set wider than the UI's top-N so the frontend
        can re-sort by notional (volume * avg_price * 100) without losing
        high-notional rows that sit outside the rank-ordered first 10."""

        # LEFT JOIN option_contract_snapshots to surface today's ask/bid/mid
        # breakdown — /oi-change never returns prev_* side volumes (all NULL),
        # so per-contract aggressor classification has to come from
        # /option-contracts via this join.
        sql = (
            f"SELECT e.underlying_symbol, e.option_symbol, e.curr_date, e.last_date, "
            "e.curr_oi, e.last_oi, e.oi_diff_plain, e.oi_change, e.volume, e.trades, "
            "e.avg_price, e.last_fill, e.days_of_oi_increases, e.days_of_vol_greater_than_oi, "
            "e.percentage_of_total, e.rnk, "
            "e.prev_ask_volume, e.prev_bid_volume, e.prev_mid_volume, e.prev_neutral_volume, "
            "e.prev_multi_leg_volume, e.prev_stock_multi_leg_volume, "
            "e.prev_total_premium, e.last_ask, e.last_bid, "
            "s.ask_volume, s.bid_volume, s.mid_volume, s.no_side_volume "
            f"FROM {self._schema}.oi_change_events e "
            f"LEFT JOIN {self._schema}.option_contract_snapshots s "
            "  ON s.run_id = e.run_id AND s.option_symbol = e.option_symbol "
            "WHERE e.run_id = %s "
            "ORDER BY (COALESCE(e.volume, 0) * COALESCE(e.avg_price, 0)) DESC NULLS LAST, e.rnk ASC "
            "LIMIT %s"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (run_id, limit))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def fetch_max_pain_rows(self, run_id: int, ticker: str) -> list[dict[str, Any]]:
        sql = (
            f"SELECT expiry, max_pain, close, open, next_upper_strike, next_lower_strike "
            f"FROM {self._schema}.max_pain_by_expiry "
            "WHERE run_id = %s AND ticker = %s ORDER BY expiry"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (run_id, ticker))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def fetch_option_contracts(self, run_id: int, ticker: str) -> list[dict[str, Any]]:
        sql = (
            f"SELECT option_symbol, last_price, nbbo_bid, nbbo_ask, "
            "implied_volatility, open_interest, volume, total_premium "
            f"FROM {self._schema}.option_contract_snapshots "
            "WHERE run_id = %s AND ticker = %s "
            "ORDER BY total_premium DESC NULLS LAST"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (run_id, ticker))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def fetch_option_contracts_rich(
        self, run_id: int, ticker: str
    ) -> list[dict[str, Any]]:
        sql = (
            f"SELECT option_symbol, last_price, nbbo_bid, nbbo_ask, "
            "implied_volatility, open_interest, prev_oi, volume, ask_volume, "
            "bid_volume, mid_volume, multi_leg_volume, stock_multi_leg_volume, "
            "floor_volume, sweep_volume, no_side_volume, avg_price, high_price, "
            "low_price, total_premium "
            f"FROM {self._schema}.option_contract_snapshots "
            "WHERE run_id = %s AND ticker = %s "
            "ORDER BY total_premium DESC NULLS LAST"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (run_id, ticker))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def upsert_trade_insight_snapshot(
        self,
        *,
        run_id: int,
        ticker: str,
        as_of: datetime | None,
        assembler_version: str,
        input_hash: str,
        payload: dict[str, Any],
    ) -> int:
        header = payload.get("header") or {}
        source_reconciliation = payload.get("source_reconciliation") or {}
        sql = (
            f"INSERT INTO {self._schema}.trade_insight_snapshots "
            "(run_id, ticker, as_of, assembler_version, input_hash, "
            "source_reconciliation_status, confidence_label, data_quality_label, "
            "preferred_idea_id, payload_jsonb) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (run_id, ticker, assembler_version, input_hash) "
            "DO UPDATE SET payload_jsonb=EXCLUDED.payload_jsonb, "
            "source_reconciliation_status=EXCLUDED.source_reconciliation_status, "
            "confidence_label=EXCLUDED.confidence_label, "
            "data_quality_label=EXCLUDED.data_quality_label, "
            "preferred_idea_id=EXCLUDED.preferred_idea_id "
            "RETURNING snapshot_id"
        )
        with self._conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    run_id,
                    ticker.upper(),
                    as_of,
                    assembler_version,
                    input_hash,
                    source_reconciliation.get("status"),
                    header.get("confidence_label"),
                    header.get("data_quality_label"),
                    header.get("preferred_idea_id"),
                    Jsonb(payload),
                ),
            )
            row = cur.fetchone()
        assert row is not None
        return int(row[0])

    def replace_trade_insight_candidates(
        self,
        *,
        snapshot_id: int,
        run_id: int,
        ticker: str,
        candidates: list[dict[str, Any]],
    ) -> int:
        delete_sql = (
            f"DELETE FROM {self._schema}.trade_insight_candidates "
            "WHERE snapshot_id = %s"
        )
        insert_sql = (
            f"INSERT INTO {self._schema}.trade_insight_candidates "
            "(snapshot_id, idea_id, ticker, run_id, structure, expression_type, rank, "
            "status, net_credit_debit, max_profit, max_loss, edge_source, risk_flags, "
            "legs_jsonb, candidate_jsonb) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
        )
        with self._conn.cursor() as cur:
            cur.execute(delete_sql, (snapshot_id,))
            for c in candidates:
                cur.execute(
                    insert_sql,
                    (
                        snapshot_id,
                        c["idea_id"],
                        ticker.upper(),
                        run_id,
                        c["structure"],
                        c.get("expression_type"),
                        c["rank"],
                        c["status"],
                        c.get("net_credit_debit"),
                        c.get("max_profit"),
                        c.get("max_loss"),
                        c.get("edge_source"),
                        list(c.get("risk_flags") or []),
                        Jsonb(c.get("legs") or []),
                        Jsonb(c),
                    ),
                )
        return len(candidates)

    def fetch_trade_insight_snapshot(self, snapshot_id: int) -> dict[str, Any] | None:
        sql = (
            f"SELECT * FROM {self._schema}.trade_insight_snapshots "
            "WHERE snapshot_id = %s"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (snapshot_id,))
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d.name for d in cur.description or []]
            return dict(zip(cols, row, strict=False))

    def fetch_latest_trade_insight_snapshot_for_hash(
        self,
        *,
        ticker: str,
        input_hash: str,
        assembler_version: str,
    ) -> dict[str, Any] | None:
        sql = (
            f"SELECT * FROM {self._schema}.trade_insight_snapshots "
            "WHERE ticker = %s AND input_hash = %s AND assembler_version = %s "
            "ORDER BY created_at DESC, snapshot_id DESC "
            "LIMIT 1"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker.upper(), input_hash, assembler_version))
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d.name for d in cur.description or []]
            return dict(zip(cols, row, strict=False))

    def find_completed_trade_insight_ai_analysis(
        self,
        *,
        ticker: str,
        analysis_input_hash: str,
        prompt_version: str,
        model: str,
    ) -> dict[str, Any] | None:
        sql = (
            f"SELECT * FROM {self._schema}.trade_insight_ai_analyses "
            "WHERE ticker = %s "
            "AND analysis_input_hash = %s "
            "AND prompt_version = %s "
            "AND model = %s "
            "AND status = 'succeeded' "
            "ORDER BY finished_at DESC NULLS LAST, requested_at DESC "
            "LIMIT 1"
        )
        with self._conn.cursor() as cur:
            cur.execute(
                sql,
                (ticker.upper(), analysis_input_hash, prompt_version, model),
            )
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d.name for d in cur.description or []]
            return dict(zip(cols, row, strict=False))

    def find_reusable_trade_insight_ai_analysis(
        self,
        *,
        ticker: str,
        analysis_input_hash: str,
        prompt_version: str,
        model: str,
    ) -> dict[str, Any] | None:
        sql = (
            f"SELECT * FROM {self._schema}.trade_insight_ai_analyses "
            "WHERE ticker = %s "
            "AND analysis_input_hash = %s "
            "AND prompt_version = %s "
            "AND model = %s "
            "AND status IN ('queued', 'running', 'succeeded') "
            "ORDER BY "
            "  CASE status WHEN 'succeeded' THEN 0 WHEN 'running' THEN 1 ELSE 2 END, "
            "  finished_at DESC NULLS LAST, "
            "  started_at DESC NULLS LAST, "
            "  requested_at DESC "
            "LIMIT 1"
        )
        with self._conn.cursor() as cur:
            cur.execute(
                sql,
                (ticker.upper(), analysis_input_hash, prompt_version, model),
            )
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d.name for d in cur.description or []]
            return dict(zip(cols, row, strict=False))

    def find_latest_succeeded_trade_insight_ai_analysis(
        self,
        *,
        ticker: str,
    ) -> dict[str, Any] | None:
        sql = (
            f"SELECT * FROM {self._schema}.trade_insight_ai_analyses "
            "WHERE ticker = %s AND status = 'succeeded' "
            "ORDER BY finished_at DESC NULLS LAST, requested_at DESC "
            "LIMIT 1"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker.upper(),))
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d.name for d in cur.description or []]
            return dict(zip(cols, row, strict=False))

    def find_latest_trade_insight_ai_analysis(
        self,
        *,
        ticker: str,
        prompt_version: str,
        model: str,
    ) -> dict[str, Any] | None:
        sql = (
            f"SELECT * FROM {self._schema}.trade_insight_ai_analyses "
            "WHERE ticker = %s "
            "AND prompt_version = %s "
            "AND model = %s "
            "AND status IN ('queued', 'running', 'succeeded') "
            "ORDER BY "
            "  CASE status WHEN 'running' THEN 0 WHEN 'queued' THEN 1 ELSE 2 END, "
            "  started_at DESC NULLS LAST, "
            "  requested_at DESC, "
            "  finished_at DESC NULLS LAST "
            "LIMIT 1"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker.upper(), prompt_version, model))
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d.name for d in cur.description or []]
            return dict(zip(cols, row, strict=False))

    def enqueue_trade_insight_ai_analysis(
        self,
        *,
        snapshot_id: int,
        ticker: str,
        run_id: int,
        trade_insights_input_hash: str,
        analysis_input_hash: str,
        analysis_input: dict[str, Any],
        prompt_version: str,
        model: str,
    ) -> str:
        sql = (
            f"INSERT INTO {self._schema}.trade_insight_ai_analyses "
            "(snapshot_id, ticker, run_id, trade_insights_input_hash, "
            "analysis_input_hash, analysis_input_jsonb, prompt_version, model, status) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'queued') "
            "ON CONFLICT (ticker, analysis_input_hash, prompt_version, model) "
            "WHERE status IN ('queued', 'running') "
            "DO NOTHING "
            "RETURNING analysis_id"
        )
        with self._conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    snapshot_id,
                    ticker.upper(),
                    run_id,
                    trade_insights_input_hash,
                    analysis_input_hash,
                    Jsonb(analysis_input),
                    prompt_version,
                    model,
                ),
            )
            row = cur.fetchone()
            if row is None:
                cur.execute(
                    f"SELECT analysis_id FROM {self._schema}.trade_insight_ai_analyses "
                    "WHERE ticker = %s "
                    "AND analysis_input_hash = %s "
                    "AND prompt_version = %s "
                    "AND model = %s "
                    "AND status IN ('queued', 'running') "
                    "ORDER BY started_at DESC NULLS LAST, requested_at DESC "
                    "LIMIT 1",
                    (ticker.upper(), analysis_input_hash, prompt_version, model),
                )
                row = cur.fetchone()
        assert row is not None
        return str(row[0])

    def claim_next_trade_insight_ai_analysis(
        self,
        *,
        stale_running_before: datetime | None = None,
    ) -> dict[str, Any] | None:
        sql = (
            f"UPDATE {self._schema}.trade_insight_ai_analyses "
            "SET status = 'running', started_at = now(), finished_at = NULL, error_message = NULL "
            "WHERE analysis_id = ("
            f"  SELECT analysis_id FROM {self._schema}.trade_insight_ai_analyses "
            "  WHERE status = 'queued' "
            "     OR ("
            "       status = 'running' "
            "       AND %s::timestamptz IS NOT NULL "
            "       AND (started_at IS NULL OR started_at < %s::timestamptz)"
            "     ) "
            "  ORDER BY CASE WHEN status = 'running' THEN 0 ELSE 1 END, requested_at "
            "  FOR UPDATE SKIP LOCKED "
            "  LIMIT 1"
            ") "
            "RETURNING *"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (stale_running_before, stale_running_before))
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d.name for d in cur.description or []]
            return dict(zip(cols, row, strict=False))

    def prepare_trade_insight_ai_analysis(
        self,
        analysis_id: str,
        *,
        prompt_text: str,
        prompt_payload: dict[str, Any],
        output_schema: dict[str, Any],
        produced_at: datetime,
    ) -> None:
        sql = (
            f"UPDATE {self._schema}.trade_insight_ai_analyses "
            "SET prompt_text = %s, "
            "prompt_payload_jsonb = %s, "
            "output_schema_jsonb = %s, "
            "produced_at = %s "
            "WHERE analysis_id = %s"
        )
        with self._conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    prompt_text,
                    Jsonb(prompt_payload),
                    Jsonb(output_schema),
                    produced_at,
                    analysis_id,
                ),
            )

    def complete_trade_insight_ai_analysis(
        self,
        analysis_id: str,
        *,
        outcome: dict[str, Any],
        markdown: str,
    ) -> None:
        sql = (
            f"UPDATE {self._schema}.trade_insight_ai_analyses "
            "SET status = 'succeeded', "
            "outcome_jsonb = %s, "
            "markdown = %s, "
            "error_message = NULL, "
            "finished_at = now() "
            "WHERE analysis_id = %s"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (Jsonb(outcome), markdown, analysis_id))

    def fail_trade_insight_ai_analysis(
        self,
        analysis_id: str,
        error_message: str,
    ) -> None:
        sql = (
            f"UPDATE {self._schema}.trade_insight_ai_analyses "
            "SET status = 'failed', "
            "error_message = %s, "
            "finished_at = now() "
            "WHERE analysis_id = %s"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (error_message[:4000], analysis_id))

    def get_trade_insight_ai_analysis(
        self,
        analysis_id: str,
        ticker: str | None = None,
    ) -> dict[str, Any] | None:
        sql = f"SELECT * FROM {self._schema}.trade_insight_ai_analyses WHERE analysis_id = %s"
        params: tuple[Any, ...]
        if ticker is not None:
            sql += " AND ticker = %s"
            params = (analysis_id, ticker.upper())
        else:
            params = (analysis_id,)
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d.name for d in cur.description or []]
            return dict(zip(cols, row, strict=False))

    def fetch_dark_pool_summary(self, run_id: int) -> tuple[int, Decimal]:
        sql = (
            f"SELECT COUNT(*), COALESCE(SUM(premium), 0) "
            f"FROM {self._schema}.dark_pool_events WHERE run_id = %s"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (run_id,))
            row = cur.fetchone()
        assert row is not None
        return int(row[0]), Decimal(str(row[1] or 0))

    def fetch_short_interest_snapshot(self, run_id: int) -> dict[str, Any] | None:
        sql = (
            f"SELECT ticker, name, snapshot_at, short_shares_available, "
            "fee_rate, rebate_rate "
            f"FROM {self._schema}.short_interest_snapshots WHERE run_id = %s"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (run_id,))
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d.name for d in cur.description or []]
            return dict(zip(cols, row, strict=False))

    # ------------------------------------------------------------------
    # Row-count helpers (used by integration test)
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
    def insert_scan_universe(
        self,
        run_id: int,
        tickers: Iterable[str],
        source: str = "hardcoded_s2",
    ) -> int:
        rows = [t.upper() for t in tickers]
        if not rows:
            return 0
        sql = (
            f"INSERT INTO {self._schema}.scan_universe (run_id, ticker, source) "
            "VALUES (%s, %s, %s) "
            "ON CONFLICT (run_id, ticker) DO NOTHING"
        )
        with self._conn.cursor() as cur:
            for t in rows:
                cur.execute(sql, (run_id, t, source))
        return len(rows)

    def insert_scan_results(
        self,
        run_id: int,
        results: Iterable[models.ScanTickerResult],
    ) -> int:
        rows = list(results)
        if not rows:
            return 0
        sql = (
            f"INSERT INTO {self._schema}.scan_results ("
            "run_id, ticker, market_date, setup_type, direction, score, "
            "net_call_premium, net_put_premium, net_premium, "
            "bullish_premium, bearish_premium, call_premium, put_premium, "
            "put_call_ratio, iv_rank, volatility, iv30d, "
            "implied_move, implied_move_perc, "
            "gex_net_change, gex_ratio, variance_risk_premium, "
            "total_open_interest, relative_volume, next_earnings_date, "
            "sector, marketcap, "
            "signals_present, confirmations, warnings, notes) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
            "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (run_id, ticker) DO UPDATE SET "
            "setup_type=EXCLUDED.setup_type, direction=EXCLUDED.direction, "
            "score=EXCLUDED.score, signals_present=EXCLUDED.signals_present, "
            "confirmations=EXCLUDED.confirmations, warnings=EXCLUDED.warnings, "
            "notes=EXCLUDED.notes"
        )
        with self._conn.cursor() as cur:
            for r in rows:
                sr = r.screener_row
                market_date = sr.date if sr is not None else None
                volatility = sr.volatility if sr is not None else None
                iv30d = sr.iv30d if sr is not None else None
                implied_move = sr.implied_move if sr is not None else None
                implied_move_perc = sr.implied_move_perc if sr is not None else None
                gex_ratio = sr.gex_ratio if sr is not None else None
                bullish_premium = sr.bullish_premium if sr is not None else None
                bearish_premium = sr.bearish_premium if sr is not None else None
                call_premium = sr.call_premium if sr is not None else None
                put_premium = sr.put_premium if sr is not None else None
                put_call_ratio = sr.put_call_ratio if sr is not None else None
                marketcap = sr.marketcap if sr is not None else None
                cur.execute(
                    sql,
                    (
                        run_id,
                        r.ticker,
                        market_date,
                        r.setup_type,
                        r.direction,
                        r.score,
                        r.net_call_premium,
                        r.net_put_premium,
                        r.net_premium,
                        bullish_premium,
                        bearish_premium,
                        call_premium,
                        put_premium,
                        put_call_ratio,
                        r.iv_rank,
                        volatility,
                        iv30d,
                        implied_move,
                        implied_move_perc,
                        r.gex_net_change,
                        gex_ratio,
                        r.variance_risk_premium,
                        r.total_open_interest,
                        r.relative_volume,
                        r.next_earnings_date,
                        r.sector,
                        marketcap,
                        list(r.signals_present),
                        list(r.confirmations),
                        list(r.warnings),
                        r.notes,
                    ),
                )
        return len(rows)

    def fetch_scan_universe(self, run_id: int) -> list[dict[str, Any]]:
        sql = (
            f"SELECT ticker, source FROM {self._schema}.scan_universe "
            "WHERE run_id = %s ORDER BY ticker"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (run_id,))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def fetch_scan_results(self, run_id: int) -> list[dict[str, Any]]:
        sql = (
            f"SELECT run_id, ticker, market_date, setup_type, direction, score, "
            "net_call_premium, net_put_premium, net_premium, "
            "bullish_premium, bearish_premium, call_premium, put_premium, "
            "put_call_ratio, iv_rank, volatility, iv30d, "
            "implied_move, implied_move_perc, "
            "gex_net_change, gex_ratio, variance_risk_premium, "
            "total_open_interest, relative_volume, next_earnings_date, "
            "sector, marketcap, "
            "signals_present, confirmations, warnings, notes "
            f"FROM {self._schema}.scan_results "
            "WHERE run_id = %s "
            "ORDER BY score DESC, ticker ASC"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (run_id,))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def get_last_full_scan_finished_at(self) -> datetime | None:
        """Latest scan_runs.finished_at where status='ok'. Used by /api/health."""
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT MAX(finished_at) FROM {self._schema}.scan_runs
                WHERE status='ok' AND finished_at IS NOT NULL
                """
            )
            row = cur.fetchone()
        return row[0] if row and row[0] else None

    def list_runs_for_ticker(
        self, ticker: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Return recent scan_runs rows for a ticker, newest first."""
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT run_id, started_at, finished_at, status
                FROM {self._schema}.scan_runs
                WHERE ticker = %s
                ORDER BY run_id DESC
                LIMIT %s
                """,
                (ticker.upper(), limit),
            )
            return [
                {
                    "run_id": int(row[0]),
                    "scanned_at": row[1],
                    "finished_at": row[2],
                    "status": row[3],
                }
                for row in cur.fetchall()
            ]

    def latest_scan_run_id(self) -> int:
        """Return the highest run_id that has scan_results rows, or 0 if none."""
        sql = (
            f"SELECT run_id FROM {self._schema}.scan_results "
            "ORDER BY run_id DESC LIMIT 1"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql)
            row = cur.fetchone()
            return int(row[0]) if row else 0

    # ------------------------------------------------------------------
    # S3+: watchlist CRUD
    # ------------------------------------------------------------------
    def list_active_watchlist(self) -> list[WatchlistRow]:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT ticker, sector, notes, pinned, sort_rank, added_at, removed_at
                FROM {self._schema}.watchlist
                WHERE removed_at IS NULL
                ORDER BY sort_rank, ticker
                """
            )
            return [WatchlistRow(*row) for row in cur.fetchall()]

    def add_watchlist_ticker(
        self,
        *,
        ticker: str,
        sector: str,
        notes: str | None = None,
        sort_rank: int = 0,
        pinned: bool = False,
    ) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {self._schema}.watchlist
                  (ticker, sector, notes, sort_rank, pinned)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (ticker) DO UPDATE
                  SET sector=EXCLUDED.sector, notes=EXCLUDED.notes,
                      sort_rank=EXCLUDED.sort_rank, pinned=EXCLUDED.pinned,
                      removed_at=NULL
                """,
                (ticker, sector, notes, sort_rank, pinned),
            )
        self._conn.commit()

    def soft_delete_watchlist_ticker(self, ticker: str) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"UPDATE {self._schema}.watchlist SET removed_at=NOW() WHERE ticker=%s",
                (ticker,),
            )
        self._conn.commit()

    def patch_watchlist_ticker(
        self,
        ticker: str,
        *,
        sector: str | None = None,
        notes: str | None = None,
        pinned: bool | None = None,
        sort_rank: int | None = None,
    ) -> None:
        sets: list[str] = []
        vals: list[Any] = []
        for col, val in (
            ("sector", sector),
            ("notes", notes),
            ("pinned", pinned),
            ("sort_rank", sort_rank),
        ):
            if val is not None:
                sets.append(f"{col}=%s")
                vals.append(val)
        if not sets:
            return
        vals.append(ticker)
        with self._conn.cursor() as cur:
            cur.execute(
                f"UPDATE {self._schema}.watchlist SET {', '.join(sets)} WHERE ticker=%s",
                vals,
            )
        self._conn.commit()

    # ---- watchlist_card ----
    def upsert_watchlist_card(
        self,
        *,
        ticker: str,
        run_id: int,
        scanned_at: datetime,
        spot: Decimal | None = None,
        **fields: Any,
    ) -> None:
        """Insert or replace the per-ticker card row.

        `updated_at` is DB-owned (default NOW() on insert; refreshed by the
        conflict branch). It is NOT part of the column list, so INSERT cols
        and VALUES placeholders have matching arity.
        """
        cols = ["ticker", "run_id", "scanned_at", "spot", *fields.keys()]
        vals = [ticker, run_id, scanned_at, spot, *fields.values()]
        placeholders = ", ".join(["%s"] * len(cols))
        updates = ", ".join(f"{c}=EXCLUDED.{c}" for c in cols if c != "ticker")
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {self._schema}.watchlist_card ({", ".join(cols)})
                VALUES ({placeholders})
                ON CONFLICT (ticker) DO UPDATE SET {updates}, updated_at=NOW()
                """,
                vals,
            )
        self._conn.commit()

    def get_watchlist_card(self, ticker: str) -> WatchlistCardRow | None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"SELECT * FROM {self._schema}.watchlist_card WHERE ticker=%s",
                (ticker,),
            )
            row = cur.fetchone()
            return WatchlistCardRow.from_db(row, cur.description) if row else None

    def list_watchlist_cards(self) -> list[WatchlistCardRow]:
        """Return one row per active watchlist ticker.

        LEFT JOIN from watchlist → watchlist_card so tickers that haven't been
        scanned yet still appear (with scan-derived fields = None). The page
        renders them as 'no data' placeholders, which is preferable to making
        them invisible while a full_scan is still chewing through the queue.
        Also LEFT JOINs intraday_quotes so a 15-min-delayed spot price shows
        up even before the first full scan for that ticker.
        """
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                WITH active_jobs AS (
                  SELECT
                    id, ticker, status, requested_at, started_at,
                    row_number() OVER (
                      ORDER BY priority DESC, requested_at ASC, id ASC
                    ) AS queue_position
                  FROM {self._schema}.jobs
                  WHERE status IN ('queued', 'running')
                ),
                latest_market_caps AS (
                  SELECT DISTINCT ON (ticker)
                    ticker,
                    marketcap
                  FROM {self._schema}.scan_results
                  WHERE marketcap IS NOT NULL
                  ORDER BY ticker, run_id DESC
                ),
                latest_screener_sizes AS (
                  SELECT DISTINCT ON (r.ticker)
                    r.ticker,
                    p.payload_jsonb->'data'->0->>'marketcap' AS market_cap
                  FROM {self._schema}.scan_runs r
                  JOIN {self._schema}.api_request_audit a ON r.run_id = a.run_id
                  JOIN {self._schema}.raw_payloads p ON a.audit_id = p.audit_id
                  WHERE a.endpoint_slug = 'bulk_screener_stocks'
                    AND jsonb_typeof(p.payload_jsonb->'data') = 'array'
                    AND p.payload_jsonb->'data'->0->>'marketcap' IS NOT NULL
                  ORDER BY r.ticker, r.run_id DESC
                ),
                latest_etf_aum AS (
                  SELECT DISTINCT ON (r.ticker)
                    r.ticker,
                    p.payload_jsonb->'data'->>'aum' AS aum
                  FROM {self._schema}.scan_runs r
                  JOIN {self._schema}.api_request_audit a ON r.run_id = a.run_id
                  JOIN {self._schema}.raw_payloads p ON a.audit_id = p.audit_id
                  WHERE a.endpoint_slug = 'etf_info'
                    AND jsonb_typeof(p.payload_jsonb->'data') = 'object'
                    AND p.payload_jsonb->'data'->>'aum' IS NOT NULL
                  ORDER BY r.ticker, r.run_id DESC
                )
                SELECT
                  w.ticker, w.sector, w.pinned, w.sort_rank,
                  c.run_id, c.scanned_at,
                  CASE
                    WHEN q.price IS NOT NULL
                      AND (c.spot_quoted_at IS NULL OR q.quoted_at >= c.spot_quoted_at)
                      THEN q.price
                    ELSE c.spot
                  END                                                       AS spot,
                  CASE
                    WHEN q.price IS NOT NULL
                      AND (c.spot_quoted_at IS NULL OR q.quoted_at >= c.spot_quoted_at)
                      THEN q.quoted_at
                    ELSE c.spot_quoted_at
                  END                                                       AS spot_quoted_at,
                  CASE
                    WHEN q.price IS NOT NULL
                      AND (c.spot_quoted_at IS NULL OR q.quoted_at >= c.spot_quoted_at)
                      THEN 'massive.com_intraday'
                    ELSE c.spot_source
                  END                                                       AS spot_source,
                  c.iv_atm, c.iv_rank,
                  c.setup_type, c.setup_direction, c.setup_score,
                  c.aggression_pct,
                  c.ret_1d, c.ret_1w, c.ret_30d,
                  COALESCE(
                    sr.aggregates->>'market_cap',
                    lmc.marketcap::text,
                    lss.market_cap
                  ) AS market_cap,
                  COALESCE(sr.aggregates->>'aum', lea.aum) AS aum,
                  c.gex_flip_distance, c.gex_flip_price, c.gex_per_1pct_move,
                  c.max_gex_strike, c.gex_expiring_pct, c.gex_expiring_date,
                  c.skew_25d_30dte,
                  c.call_oi_total, c.put_oi_total, c.pcr_oi, c.pcr_vol,
                  c.pcr_delta_30d,
                  j.id AS active_job_id,
                  j.status AS active_job_status,
                  j.queue_position AS active_job_queue_position,
                  j.requested_at AS active_job_requested_at,
                  j.started_at AS active_job_started_at
                FROM {self._schema}.watchlist w
                LEFT JOIN {self._schema}.watchlist_card c ON w.ticker = c.ticker
                LEFT JOIN {self._schema}.scan_runs sr ON c.run_id = sr.run_id
                LEFT JOIN latest_market_caps lmc ON w.ticker = lmc.ticker
                LEFT JOIN latest_screener_sizes lss ON w.ticker = lss.ticker
                LEFT JOIN latest_etf_aum lea ON w.ticker = lea.ticker
                LEFT JOIN {self._schema}.intraday_quote q ON w.ticker = q.ticker
                LEFT JOIN active_jobs j ON w.ticker = j.ticker
                WHERE w.removed_at IS NULL
                ORDER BY w.pinned DESC, w.sort_rank, w.ticker
                """
            )
            return [
                WatchlistCardRow.from_db(row, cur.description) for row in cur.fetchall()
            ]

    # ---- daily_ohlc ----
    def upsert_daily_ohlc(
        self,
        *,
        ticker: str,
        date: _date,
        open: Decimal | None,
        high: Decimal | None,
        low: Decimal | None,
        close: Decimal,
        volume: int | None,
        source: str,
    ) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {self._schema}.daily_ohlc
                  (ticker, date, open, high, low, close, volume, source)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (ticker, date) DO UPDATE
                  SET open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low,
                      close=EXCLUDED.close, volume=EXCLUDED.volume,
                      source=EXCLUDED.source, fetched_at=NOW()
                """,
                (ticker, date, open, high, low, close, volume, source),
            )
        self._conn.commit()

    def list_daily_ohlc(self, ticker: str, *, limit: int = 30) -> list[DailyOhlcRow]:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT ticker, date, open, high, low, close, volume, source, fetched_at
                FROM {self._schema}.daily_ohlc
                WHERE ticker=%s
                ORDER BY date DESC
                LIMIT %s
                """,
                (ticker, limit),
            )
            return [DailyOhlcRow(*row) for row in cur.fetchall()]

    # ---- intraday_quote ----
    def upsert_intraday_quote(
        self, ticker: str, price: Decimal, quoted_at: datetime
    ) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {self._schema}.intraday_quote (ticker, price, quoted_at)
                VALUES (%s, %s, %s)
                ON CONFLICT (ticker) DO UPDATE
                  SET price=EXCLUDED.price, quoted_at=EXCLUDED.quoted_at, fetched_at=NOW()
                """,
                (ticker, price, quoted_at),
            )
        self._conn.commit()

    def get_intraday_quote(self, ticker: str) -> IntradayQuoteRow | None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT ticker, price, quoted_at, fetched_at
                FROM {self._schema}.intraday_quote WHERE ticker=%s
                """,
                (ticker,),
            )
            row = cur.fetchone()
            return IntradayQuoteRow(*row) if row else None

    def get_latest_intraday_quote_times(self) -> tuple[datetime, datetime] | None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT MAX(quoted_at), MAX(fetched_at)
                FROM {self._schema}.intraday_quote
                """
            )
            row = cur.fetchone()
        if row and row[0] is not None and row[1] is not None:
            return (row[0], row[1])
        return None

    # ---- pcr_history ----
    def append_pcr_history(
        self,
        ticker: str,
        snapshot_date: _date,
        pcr_oi: Decimal | None,
        pcr_vol: Decimal | None,
    ) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {self._schema}.pcr_history (ticker, snapshot_date, pcr_oi, pcr_vol)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (ticker, snapshot_date) DO UPDATE
                  SET pcr_oi=EXCLUDED.pcr_oi, pcr_vol=EXCLUDED.pcr_vol
                """,
                (ticker, snapshot_date, pcr_oi, pcr_vol),
            )
        self._conn.commit()

    def get_pcr_history_30d_ago(
        self, ticker: str, today: _date
    ) -> PcrHistoryRow | None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT ticker, snapshot_date, pcr_oi, pcr_vol
                FROM {self._schema}.pcr_history
                WHERE ticker=%s AND snapshot_date <= %s - INTERVAL '30 days'
                ORDER BY snapshot_date DESC
                LIMIT 1
                """,
                (ticker, today),
            )
            row = cur.fetchone()
            return PcrHistoryRow(*row) if row else None

    # ---- jobs ----
    def enqueue_rescan_job(self, ticker: str, *, priority: int = 0) -> str:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {self._schema}.jobs (ticker, status, priority)
                VALUES (%s, 'queued', %s)
                ON CONFLICT (ticker) WHERE status IN ('queued', 'running')
                DO UPDATE SET
                    priority = GREATEST(
                        {self._schema}.jobs.priority,
                        EXCLUDED.priority
                    ),
                    requested_at = EXCLUDED.requested_at
                RETURNING id
                """,
                (ticker, priority),
            )
            row = cur.fetchone()
            assert row is not None
            job_id = row[0]
        self._conn.commit()
        return str(job_id)

    def claim_next_queued_job(self) -> JobRow | None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {self._schema}.jobs
                SET status='running',
                    started_at=NOW(),
                    claim_token=gen_random_uuid()
                WHERE id = (
                  SELECT id FROM {self._schema}.jobs
                  WHERE status='queued'
                  ORDER BY priority DESC, requested_at ASC, id ASC
                  FOR UPDATE SKIP LOCKED
                  LIMIT 1
                )
                RETURNING id, ticker, status, run_id, error,
                          requested_at, started_at, finished_at, claim_token
                """
            )
            row = cur.fetchone()
        self._conn.commit()
        return JobRow(*row) if row else None

    def requeue_stale_running_jobs(self, older_than: timedelta) -> int:
        # Clear claim_token so the original worker's stored token will not
        # match anything if/when it tries mark_job_done later (review
        # 2026-05-16, B1; claim-token approach per codex review).
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {self._schema}.jobs
                SET status='queued',
                    started_at=NULL,
                    error=NULL,
                    claim_token=NULL
                WHERE status='running'
                  AND started_at < NOW() - %s
                """,
                (older_than,),
            )
            count = cur.rowcount
        self._conn.commit()
        return count

    def mark_job_done(self, job_id: str, run_id: int, claim_token: Any) -> None:
        # Claim-token guard against the requeue race (review 2026-05-16, B1):
        # if requeue_stale_running_jobs cleared our token, or another worker
        # has since reclaimed (with a fresh token), our update must be rejected.
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {self._schema}.jobs
                SET status='done', run_id=%s, finished_at=NOW()
                WHERE id=%s AND claim_token=%s
                """,
                (run_id, job_id, claim_token),
            )
            if cur.rowcount == 0:
                logger.warning(
                    "mark_job_done lost claim on job_id=%s "
                    "(token mismatch; another worker may have reclaimed)",
                    job_id,
                )
        self._conn.commit()

    def mark_job_failed(self, job_id: str, error: str, claim_token: Any) -> None:
        # Claim-token guard (review 2026-05-16, B1).
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {self._schema}.jobs
                SET status='failed', error=%s, finished_at=NOW()
                WHERE id=%s AND claim_token=%s
                """,
                (error[:2000], job_id, claim_token),
            )
            if cur.rowcount == 0:
                logger.warning(
                    "mark_job_failed lost claim on job_id=%s "
                    "(token mismatch; another worker may have reclaimed)",
                    job_id,
                )
        self._conn.commit()

    def get_rescan_queue_summary(self) -> RescanQueueSummaryRow:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                  count(*) FILTER (WHERE status IN ('queued', 'running')) AS total,
                  count(*) FILTER (WHERE status = 'queued') AS queued,
                  count(*) FILTER (WHERE status = 'running') AS running,
                  min(requested_at) FILTER (
                    WHERE status IN ('queued', 'running')
                  ) AS oldest_requested_at
                FROM {self._schema}.jobs
                """
            )
            row = cur.fetchone()
        assert row is not None
        return RescanQueueSummaryRow(
            total=row[0],
            queued=row[1],
            running=row[2],
            oldest_requested_at=row[3],
        )

    # ---- aggregates (JSONB on scan_runs) ----
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

    def get_pcr_history_row(
        self, ticker: str, snapshot_date: _date
    ) -> PcrHistoryRow | None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT ticker, snapshot_date, pcr_oi, pcr_vol
                FROM {self._schema}.pcr_history
                WHERE ticker=%s AND snapshot_date=%s
                """,
                (ticker, snapshot_date),
            )
            row = cur.fetchone()
        return PcrHistoryRow(*row) if row else None

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
                    (since,),
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
                        window_start=since,
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

    def get_job(self, job_id: str) -> JobRow | None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT id, ticker, status, run_id, error,
                       requested_at, started_at, finished_at, claim_token
                FROM {self._schema}.jobs WHERE id=%s
                """,
                (job_id,),
            )
            row = cur.fetchone()
            return JobRow(*row) if row else None

    # ---- Volatility Tab v2 helpers (spec 2026-05-13) ----

    def upsert_index_ohlc_rows(self, bars: Iterable[Any]) -> int:
        sql = (
            f"INSERT INTO {self._schema}.index_ohlc_daily "
            "(ticker, market_date, open, high, low, close, volume) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (ticker, market_date) DO UPDATE SET "
            "open = EXCLUDED.open, high = EXCLUDED.high, "
            "low = EXCLUDED.low, close = EXCLUDED.close, "
            "volume = EXCLUDED.volume, inserted_at = now()"
        )
        rows = [
            (b.ticker, b.date, b.open, b.high, b.low, b.close, b.volume) for b in bars
        ]
        with self._conn.cursor() as cur:
            cur.executemany(sql, rows)
        return len(rows)

    def fetch_index_ohlc_series(
        self,
        ticker: str,
        *,
        start: _date | None = None,
        end: _date | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["ticker = %s"]
        params: list[Any] = [ticker]
        if start is not None:
            clauses.append("market_date >= %s")
            params.append(start)
        if end is not None:
            clauses.append("market_date <= %s")
            params.append(end)
        sql = (
            f"SELECT market_date, open, high, low, close, volume "
            f"FROM {self._schema}.index_ohlc_daily "
            f"WHERE {' AND '.join(clauses)} "
            "ORDER BY market_date ASC"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def upsert_iv_smile_rows(self, rows: Iterable[dict[str, Any]]) -> int:
        sql = (
            f"INSERT INTO {self._schema}.iv_smile_snapshots "
            "(ticker, market_date, expiry, strike, iv) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (ticker, market_date, expiry, strike) DO UPDATE SET "
            "iv = EXCLUDED.iv, inserted_at = now()"
        )
        params = [
            (r["ticker"], r["market_date"], r["expiry"], r["strike"], r.get("iv"))
            for r in rows
        ]
        with self._conn.cursor() as cur:
            cur.executemany(sql, params)
        return len(params)

    def fetch_iv_smile_latest(self, ticker: str) -> list[dict[str, Any]]:
        """All (expiry, strike, iv) for the latest market_date with smile data."""
        sql = (
            f"WITH latest AS ("
            f"  SELECT max(market_date) AS market_date "
            f"  FROM {self._schema}.iv_smile_snapshots WHERE ticker = %s) "
            f"SELECT s.expiry, s.strike, s.iv, s.market_date "
            f"FROM {self._schema}.iv_smile_snapshots s "
            f"JOIN latest l USING (market_date) "
            f"WHERE s.ticker = %s "
            f"ORDER BY s.expiry ASC, s.strike ASC"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker, ticker))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def upsert_vrp_daily_rows(self, rows: Iterable[dict[str, Any]]) -> int:
        sql = (
            f"INSERT INTO {self._schema}.vrp_daily "
            "(ticker, market_date, iv, rv, vrp, vrp_z_20) "
            "VALUES (%s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (ticker, market_date) DO UPDATE SET "
            "iv = EXCLUDED.iv, rv = EXCLUDED.rv, "
            "vrp = EXCLUDED.vrp, vrp_z_20 = EXCLUDED.vrp_z_20, "
            "inserted_at = now()"
        )
        params = [
            (
                r["ticker"],
                r["market_date"],
                r.get("iv"),
                r.get("rv"),
                r.get("vrp"),
                r.get("vrp_z_20"),
            )
            for r in rows
        ]
        with self._conn.cursor() as cur:
            cur.executemany(sql, params)
        return len(params)

    def fetch_vrp_daily_series(
        self,
        ticker: str,
        *,
        limit: int = 60,
    ) -> list[dict[str, Any]]:
        sql = (
            f"SELECT market_date, iv, rv, vrp, vrp_z_20 "
            f"FROM {self._schema}.vrp_daily "
            f"WHERE ticker = %s "
            f"ORDER BY market_date DESC LIMIT %s"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker, limit))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def upsert_stock_analytics_rows(self, rows: Iterable[dict[str, Any]]) -> int:
        sql = (
            f"INSERT INTO {self._schema}.stock_analytics_daily "
            "(ticker, market_date, rvol_21, rvol_pctile, "
            "spy_corr_21, iv_of_iv_20) "
            "VALUES (%s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (ticker, market_date) DO UPDATE SET "
            "rvol_21 = EXCLUDED.rvol_21, rvol_pctile = EXCLUDED.rvol_pctile, "
            "spy_corr_21 = EXCLUDED.spy_corr_21, "
            "iv_of_iv_20 = EXCLUDED.iv_of_iv_20, inserted_at = now()"
        )
        params = [
            (
                r["ticker"],
                r["market_date"],
                r.get("rvol_21"),
                r.get("rvol_pctile"),
                r.get("spy_corr_21"),
                r.get("iv_of_iv_20"),
            )
            for r in rows
        ]
        with self._conn.cursor() as cur:
            cur.executemany(sql, params)
        return len(params)

    def fetch_stock_analytics_series(
        self,
        ticker: str,
        *,
        limit: int = 60,
    ) -> list[dict[str, Any]]:
        sql = (
            f"SELECT market_date, rvol_21, rvol_pctile, spy_corr_21, iv_of_iv_20 "
            f"FROM {self._schema}.stock_analytics_daily "
            f"WHERE ticker = %s ORDER BY market_date DESC LIMIT %s"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker, limit))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def fetch_greeks_rows_for_smile(
        self,
        *,
        ticker: str,
        market_date: _date,
        expiry: _date,
    ) -> list[dict[str, Any]]:
        """Cache-first source for the smile chart from greeks_by_expiry_strike."""
        sql = (
            f"SELECT expiry, strike, call_volatility, put_volatility "
            f"FROM {self._schema}.greeks_by_expiry_strike "
            "WHERE ticker = %s AND market_date = %s AND expiry = %s "
            "ORDER BY strike ASC"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker, market_date, expiry))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def count_realized_vol_history(
        self,
        ticker: str,
        *,
        days: int = 365,
    ) -> int:
        sql = (
            f"SELECT count(*) FROM {self._schema}.realized_volatility_history "
            f"WHERE ticker = %s "
            f"  AND market_date >= (CURRENT_DATE - (%s || ' days')::interval)"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker, days))
            return int(cur.fetchone()[0])

    def fetch_realized_vol_history(
        self,
        ticker: str,
        *,
        days: int = 365,
    ) -> list[dict[str, Any]]:
        sql = (
            f"SELECT market_date, price, implied_volatility, realized_volatility "
            f"FROM {self._schema}.realized_volatility_history "
            f"WHERE ticker = %s "
            f"  AND market_date >= (CURRENT_DATE - (%s || ' days')::interval) "
            f"ORDER BY market_date ASC"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker, days))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def fetch_volatility_stats_history(
        self,
        ticker: str,
        *,
        days: int = 365,
    ) -> list[dict[str, Any]]:
        sql = (
            f"SELECT market_date, iv, iv_low, iv_high, iv_rank, "
            f"rv, rv_low, rv_high "
            f"FROM {self._schema}.volatility_stats_history "
            f"WHERE ticker = %s "
            f"  AND market_date >= (CURRENT_DATE - (%s || ' days')::interval) "
            f"ORDER BY market_date ASC"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker, days))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    # ---- Backfill state machine ----
    def get_volatility_backfill_status(
        self,
        ticker: str,
    ) -> dict[str, Any] | None:
        sql = (
            f"SELECT ticker, status, started_at, finished_at, error_message "
            f"FROM {self._schema}.volatility_backfill_status WHERE ticker = %s"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker,))
            row = cur.fetchone()
            if not row:
                return None
            cols = [d.name for d in cur.description or []]
            return dict(zip(cols, row, strict=False))

    def upsert_volatility_backfill_status(
        self,
        *,
        ticker: str,
        status: str,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        error_message: str | None = None,
    ) -> None:
        sql = (
            f"INSERT INTO {self._schema}.volatility_backfill_status "
            "(ticker, status, started_at, finished_at, error_message) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (ticker) DO UPDATE SET "
            "status = EXCLUDED.status, "
            "started_at = COALESCE(EXCLUDED.started_at, "
            f"  {self._schema}.volatility_backfill_status.started_at), "
            "finished_at = EXCLUDED.finished_at, "
            "error_message = EXCLUDED.error_message"
        )
        with self._conn.cursor() as cur:
            cur.execute(
                sql,
                (ticker, status, started_at, finished_at, error_message),
            )


# Re-export for convenience
__all__ = [
    "Repository",
    "WatchlistRow",
    "WatchlistCardRow",
    "DailyOhlcRow",
    "IntradayQuoteRow",
    "PcrHistoryRow",
    "JobRow",
    "RescanQueueSummaryRow",
    "ThroughputSummaryRow",
]
