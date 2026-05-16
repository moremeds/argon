"""Persistence layer: thin wrapper around psycopg cursors.

One method per insert/select. No `**kwargs` splatting from arbitrary dicts.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import date as _date
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from psycopg import sql as psql
from psycopg.types.json import Jsonb

from .. import models
from ._base import _BaseMixin

# Pure helpers live in _helpers.py since the PR-1 split. provider_day_bounds,
# status_family_for, and redact_params are imported from this module by
# sources/ohlc.py, api/client.py, api/routers/health.py, api/routers/provider_usage.py,
# and tests — keep them re-exported.
from ._helpers import (
    _nullable_float,
    _nullable_int,
    provider_day_bounds,
    redact_params,
    status_family_for,
)
from .audit import _AuditMixin

# noqa: F401 below — _aggressor_label_confidence and _flow_footprint_label
# are re-exports for scripts/backfill_flow_footprint.py which imports them
# from uw_scan.storage.repository. Removing them would break the script.
from .flow import (
    _aggressor_label_confidence,  # noqa: F401
    _flow_footprint_label,  # noqa: F401
    _FlowMixin,
)
from .health import _HealthMixin
from .jobs import _JobsMixin
from .market_data import _MarketDataMixin

# Row dataclasses live in rows.py since the PR-1 split. Re-exported here so
# existing callers (`from uw_scan.storage.repository import JobRow`) continue
# to work without changing import paths.
from .rows import (
    DailyOhlcRow,
    ExternalApiBreakdownRow,
    ExternalApiRequestRow,
    ExternalApiUsageSummary,
    IntradayQuoteRow,
    JobRow,
    PcrHistoryRow,
    RecordHealthRow,
    RescanQueueSummaryRow,
    ThroughputSummaryRow,
    WatchlistCardRow,
    WatchlistRow,
)
from .scan_outputs import _ScanOutputsMixin

__all__ = [
    "Repository",
    "DailyOhlcRow",
    "ExternalApiBreakdownRow",
    "ExternalApiRequestRow",
    "ExternalApiUsageSummary",
    "IntradayQuoteRow",
    "JobRow",
    "PcrHistoryRow",
    "RecordHealthRow",
    "RescanQueueSummaryRow",
    "ThroughputSummaryRow",
    "WatchlistCardRow",
    "WatchlistRow",
    "provider_day_bounds",
    "redact_params",
    "status_family_for",
]


def _row_for_date(
    rows: list[dict[str, Any]], market_date: _date
) -> dict[str, Any] | None:
    for row in rows:
        if row.get("market_date") == market_date:
            return row
    return None


def _iv_delta_5d(
    *, iv_rows: list[dict[str, Any]], market_date: _date
) -> Decimal | None:
    current = _row_for_date(iv_rows, market_date)
    if current is None or current.get("volatility") is None:
        return None
    cutoff = market_date - timedelta(days=5)
    prior_rows = [
        row
        for row in iv_rows
        if row.get("market_date") is not None
        and row["market_date"] <= cutoff
        and row.get("volatility") is not None
    ]
    if not prior_rows:
        return None
    prior = max(prior_rows, key=lambda row: row["market_date"])
    return current["volatility"] - prior["volatility"]


def _pin_candidate(
    *,
    chain_rows: list[dict[str, Any]],
    spot: Decimal | None,
    market_date: _date,
) -> tuple[_date, Decimal] | None:
    candidates: list[tuple[_date, Decimal, int]] = []
    for row in chain_rows:
        expiry = row.get("expiry")
        strike = row.get("strike")
        if expiry is None or strike is None:
            continue
        dte = (expiry - market_date).days
        if dte <= 0 or dte > 5:
            continue
        strike_dec = Decimal(str(strike))
        if (
            spot is not None
            and spot > 0
            and abs(strike_dec - spot) / spot > Decimal("0.02")
        ):
            continue
        oi = int(row.get("call_oi") or 0) + int(row.get("put_oi") or 0)
        candidates.append((expiry, strike_dec, oi))
    if not candidates:
        return None
    expiry, strike, _oi = max(
        candidates,
        key=lambda item: (
            item[2],
            -abs(item[1] - spot) if spot is not None else Decimal(0),
        ),
    )
    return expiry, strike


def _pin_distance_sigma(
    *,
    spot: Decimal | None,
    strike: Decimal | None,
    iv_30d: Decimal | None,
    dte_days: int | None,
) -> Decimal | None:
    if (
        spot is None
        or strike is None
        or iv_30d is None
        or dte_days is None
        or spot <= 0
        or iv_30d <= 0
        or dte_days <= 0
    ):
        return None
    sigma_to_expiry = spot * iv_30d * (Decimal(dte_days) / Decimal(365)).sqrt()
    if sigma_to_expiry <= 0:
        return None
    return (spot - strike) / sigma_to_expiry


def _median(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / Decimal(2)


def _sum_optional(values: Iterable[Decimal]) -> Decimal | None:
    seen = False
    total = Decimal(0)
    for value in values:
        seen = True
        total += value
    return total if seen else None


def _sign_label(value: Decimal | None) -> str | None:
    if value is None:
        return None
    if value > 0:
        return "positive"
    if value < 0:
        return "negative"
    return "neutral"


def _vanna_conditional_reading(
    *,
    iv_30d_delta_5d: Decimal | None,
    directional_imbalance_3d: Decimal | None,
    flow_color: str | None,
    net_gamma_sign: str | None,
) -> str:
    if iv_30d_delta_5d is None or net_gamma_sign is None:
        return "weak_noise"
    flow_is_put = flow_color == "put_heavy" or (
        directional_imbalance_3d is not None and directional_imbalance_3d < 0
    )
    flow_is_call = flow_color == "call_heavy" or (
        directional_imbalance_3d is not None and directional_imbalance_3d > 0
    )
    if iv_30d_delta_5d < 0 and flow_is_put and net_gamma_sign == "positive":
        return "grind_up"
    if iv_30d_delta_5d < 0 and flow_is_call and net_gamma_sign == "positive":
        return "reverse_selloff"
    if iv_30d_delta_5d > 0 and flow_is_put and net_gamma_sign == "negative":
        return "reflexive_sell_pressure"
    return "weak_noise"


def _charm_regime(
    *,
    pin_regime: bool | None,
    stress_override: bool,
    pin_distance_sigma: Decimal | None,
    pin_dte: int | None,
) -> str:
    if pin_regime:
        return (
            "opex_vortex"
            if pin_dte is not None
            and pin_dte <= 1
            and pin_distance_sigma is not None
            and abs(pin_distance_sigma) < Decimal("0.5")
            else "operative_magnet"
        )
    if stress_override:
        return (
            "opex_vortex" if pin_dte is not None and pin_dte <= 1 else "broken_magnet"
        )
    return "neutral"


def _oi_change_bias(rows: list[dict[str, Any]]) -> str | None:
    call_oi = Decimal(0)
    put_oi = Decimal(0)
    for row in rows:
        symbol = str(row.get("option_symbol") or "")
        diff = Decimal(row.get("oi_diff_plain") or 0)
        if "C" in symbol[-9:]:
            call_oi += diff
        elif "P" in symbol[-9:]:
            put_oi += diff
    if call_oi == 0 and put_oi == 0:
        return None
    if call_oi > put_oi:
        return "call_oi_build"
    if put_oi > call_oi:
        return "put_oi_build"
    return "mixed"


def _vrp_sign_flip_status_for_db(value: bool | str | None) -> str | None:
    if value is True:
        return "true"
    if value is False:
        return "false"
    return value


def _vrp_sign_flip_status_from_db(value: Any) -> bool | str:
    if value == "true":
        return True
    if value == "false":
        return False
    return value or "insufficient_history"


# _RECORD_HEALTH_* constants moved to health.py with _HealthMixin


logger = logging.getLogger(__name__)


class Repository(
    _AuditMixin,
    _FlowMixin,
    _HealthMixin,
    _JobsMixin,
    _MarketDataMixin,
    _ScanOutputsMixin,
    _BaseMixin,
):
    """Repository wraps a psycopg connection and exposes typed CRUD.

    Inherits __init__ and the conn property from _BaseMixin. As PR-1/2/3
    progress this class will gain per-domain mixins (_AuditMixin,
    _FlowMixin, ...); _BaseMixin stays LAST in the inheritance list."""

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

    # flow_events + flow_alerts_daily_rollup methods moved to _FlowMixin
    # _flow_alert_trade_date is now module-level in flow.py (doesn't use self)

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

    # ------------------------------------------------------------------
    # Cockpit matrix state source reads
    # ------------------------------------------------------------------
    def fetch_matrix_greeks_rows(
        self, *, ticker: str, market_date: _date
    ) -> list[dict[str, Any]]:
        sql = (
            "SELECT expiry, strike, call_vanna, put_vanna, call_charm, put_charm, "
            "call_option_symbol, put_option_symbol "
            f"FROM {self._schema}.greeks_by_expiry_strike "
            "WHERE ticker = %s AND market_date = %s "
            "  AND run_id = ("
            f"    SELECT max(run_id) FROM {self._schema}.greeks_by_expiry_strike "
            "    WHERE ticker = %s AND market_date = %s"
            "  ) "
            "ORDER BY expiry, strike"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker, market_date, ticker, market_date))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def fetch_matrix_straddle_mid_rows(
        self, *, ticker: str, market_date: _date
    ) -> list[dict[str, Any]]:
        sql = (
            "SELECT g.expiry, g.strike, "
            "(c.nbbo_bid + c.nbbo_ask) / 2 AS call_mid, "
            "(p.nbbo_bid + p.nbbo_ask) / 2 AS put_mid "
            f"FROM {self._schema}.greeks_by_expiry_strike g "
            f"LEFT JOIN {self._schema}.option_contract_snapshots c "
            "  ON c.run_id = g.run_id AND c.option_symbol = g.call_option_symbol "
            f"LEFT JOIN {self._schema}.option_contract_snapshots p "
            "  ON p.run_id = g.run_id AND p.option_symbol = g.put_option_symbol "
            "WHERE g.ticker = %s AND g.market_date = %s "
            "  AND g.run_id = ("
            f"    SELECT max(run_id) FROM {self._schema}.greeks_by_expiry_strike "
            "    WHERE ticker = %s AND market_date = %s"
            "  ) "
            "ORDER BY g.expiry ASC, g.strike ASC"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker, market_date, ticker, market_date))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def fetch_matrix_exposure_rows(
        self, *, ticker: str, market_date: _date
    ) -> list[dict[str, Any]]:
        sql = (
            "SELECT expiry, strike, dte, call_gex, put_gex, "
            "call_vanna, put_vanna, call_charm, put_charm "
            f"FROM {self._schema}.exposures_by_expiry_strike "
            "WHERE ticker = %s AND market_date = %s "
            "  AND run_id = ("
            f"    SELECT max(run_id) FROM {self._schema}.exposures_by_expiry_strike "
            "    WHERE ticker = %s AND market_date = %s"
            "  ) "
            "ORDER BY expiry, strike"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker, market_date, ticker, market_date))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def fetch_matrix_option_chain_rows(
        self, *, ticker: str, market_date: _date
    ) -> list[dict[str, Any]]:
        sql = (
            f"SELECT snapshot_date, expiry, strike, call_volume, put_volume, call_oi, put_oi "
            f"FROM {self._schema}.option_chain_per_strike "
            "WHERE ticker = %s AND snapshot_date = ("
            f"  SELECT max(snapshot_date) FROM {self._schema}.option_chain_per_strike "
            "  WHERE ticker = %s AND snapshot_date <= %s"
            ") "
            "ORDER BY expiry, strike"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker, ticker, market_date))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def fetch_matrix_skew_history(
        self, *, ticker: str, market_date: _date, days: int = 260
    ) -> list[dict[str, Any]]:
        sql = (
            f"SELECT DISTINCT ON (market_date) market_date, delta, expiry, risk_reversal "
            f"FROM {self._schema}.risk_reversal_skew_history "
            "WHERE ticker = %s AND delta = 25 "
            "  AND market_date <= %s "
            "  AND market_date >= (%s::date - (%s || ' days')::interval) "
            "ORDER BY market_date ASC, expiry ASC NULLS LAST"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker, market_date, market_date, days))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def fetch_matrix_skew_expiry_rows(
        self, *, ticker: str, market_date: _date
    ) -> list[dict[str, Any]]:
        sql = (
            "SELECT market_date, delta, expiry, risk_reversal "
            f"FROM {self._schema}.risk_reversal_skew_history "
            "WHERE ticker = %s AND delta = 25 AND market_date = %s "
            "ORDER BY expiry ASC NULLS LAST"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker, market_date))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def fetch_matrix_term_rows(
        self, *, ticker: str, market_date: _date
    ) -> list[dict[str, Any]]:
        sql = (
            f"SELECT expiry, dte, volatility, implied_move, implied_move_perc "
            f"FROM {self._schema}.iv_term_snapshots "
            "WHERE ticker = %s AND market_date = %s "
            "  AND run_id = ("
            f"    SELECT max(run_id) FROM {self._schema}.iv_term_snapshots "
            "    WHERE ticker = %s AND market_date = %s"
            "  ) "
            "ORDER BY dte ASC NULLS LAST, expiry ASC"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker, market_date, ticker, market_date))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def fetch_matrix_interpolated_iv_history(
        self, *, ticker: str, market_date: _date, days: int = 90
    ) -> list[dict[str, Any]]:
        sql = (
            "SELECT DISTINCT ON (market_date) "
            "market_date, days, percentile, volatility, implied_move_perc "
            f"FROM {self._schema}.interpolated_iv_snapshots "
            "WHERE ticker = %s "
            "  AND market_date <= %s "
            "  AND market_date >= (%s::date - (%s || ' days')::interval) "
            "ORDER BY market_date ASC, ABS(days - 30) ASC, run_id DESC"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker, market_date, market_date, days))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def fetch_matrix_realized_vol_history(
        self, *, ticker: str, market_date: _date, days: int = 90
    ) -> list[dict[str, Any]]:
        sql = (
            f"SELECT market_date, price, implied_volatility, realized_volatility "
            f"FROM {self._schema}.realized_volatility_history "
            "WHERE ticker = %s "
            "  AND market_date <= %s "
            "  AND market_date >= (%s::date - (%s || ' days')::interval) "
            "ORDER BY market_date ASC"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker, market_date, market_date, days))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def persist_vrp_30d_settlements(self, *, ticker: str, market_date: _date) -> None:
        iv_sql = (
            "SELECT volatility "
            f"FROM {self._schema}.interpolated_iv_snapshots "
            "WHERE ticker = %s AND market_date = %s "
            "ORDER BY ABS(days - 30) ASC, run_id DESC LIMIT 1"
        )
        rv_sql = (
            "SELECT market_date, realized_volatility "
            f"FROM {self._schema}.realized_volatility_history "
            "WHERE ticker = %s AND market_date >= (%s::date + INTERVAL '30 days') "
            "  AND realized_volatility IS NOT NULL "
            "ORDER BY market_date ASC LIMIT 1"
        )
        with self._conn.cursor() as cur:
            cur.execute(iv_sql, (ticker.upper(), market_date))
            iv_row = cur.fetchone()
            if iv_row is None or iv_row[0] is None:
                return
            iv_30d = iv_row[0]
            cur.execute(rv_sql, (ticker.upper(), market_date))
            rv_row = cur.fetchone()
            settlement_date = rv_row[0] if rv_row else None
            rv_subsequent = rv_row[1] if rv_row else None
            vrp_strict = iv_30d - rv_subsequent if rv_subsequent is not None else None
            cur.execute(
                f"INSERT INTO {self._schema}.vrp_30d_settlements ("
                "ticker, market_date, iv_30d, settlement_date, rv_subsequent, "
                "vrp_strict, generated_at"
                ") VALUES (%s, %s, %s, %s, %s, %s, now()) "
                "ON CONFLICT (ticker, market_date) DO UPDATE SET "
                "iv_30d=EXCLUDED.iv_30d, "
                "settlement_date=EXCLUDED.settlement_date, "
                "rv_subsequent=EXCLUDED.rv_subsequent, "
                "vrp_strict=EXCLUDED.vrp_strict, "
                "generated_at=now(), inserted_at=now()",
                (
                    ticker.upper(),
                    market_date,
                    iv_30d,
                    settlement_date,
                    rv_subsequent,
                    vrp_strict,
                ),
            )

    def fetch_vrp_30d_settlement(
        self, *, ticker: str, market_date: _date
    ) -> dict[str, Any] | None:
        sql = (
            "SELECT ticker, market_date, iv_30d, settlement_date, rv_subsequent, "
            "vrp_strict, generated_at, inserted_at "
            f"FROM {self._schema}.vrp_30d_settlements "
            "WHERE ticker = %s AND market_date = %s"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker.upper(), market_date))
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d.name for d in cur.description or []]
            return dict(zip(cols, row, strict=False))

    def fetch_matrix_oi_change_rows(
        self, *, ticker: str, market_date: _date
    ) -> list[dict[str, Any]]:
        sql = (
            "SELECT option_symbol, oi_diff_plain, oi_change, volume, trades "
            f"FROM {self._schema}.oi_change_events "
            "WHERE underlying_symbol = %s AND curr_date = %s "
            "ORDER BY ABS(COALESCE(oi_diff_plain, 0)) DESC NULLS LAST"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker.upper(), market_date))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def upsert_matrix_state_snapshot(self, state: models.MatrixState) -> None:
        sql = (
            f"INSERT INTO {self._schema}.matrix_state_snapshots ("
            "ticker, market_date, threshold_version, vanna_state, charm_state, skew_state, "
            "term_state, im_state, flow_state, vrp_state, consistency_tier, "
            "cluster_coverage_ok, term_classification, skew_25d_zscore_180d, "
            "iv_atm_30d, rv_30d, vrp, vrp_zscore_60d, implied_move_pct, "
            "front_iv, back_iv, front_back_spread, pin_distance_sigma, vrp_sign_flip_status, "
            "vrp_sign_flip_aligned_days, vanna_conditional_reading, "
            "directional_imbalance_3d, vanna_oi_change_bias, charm_regime, "
            "charm_stress_override, skew_25d_5d_change, skew_regime, "
            "skew_term_structure, single_point_bump_pct, full_curve_slope_pct, "
            "term_johnson_slope_pc1, atm_straddle_mid, implied_move_expected_abs, "
            "implied_move_event_percentile, vrp_zscore_252d, generated_at"
            ") VALUES ("
            "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
            "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
            "%s, %s, %s, %s, %s, %s, %s, %s, now()"
            ") ON CONFLICT (ticker, market_date) DO UPDATE SET "
            "threshold_version=EXCLUDED.threshold_version, "
            "vanna_state=EXCLUDED.vanna_state, "
            "charm_state=EXCLUDED.charm_state, "
            "skew_state=EXCLUDED.skew_state, "
            "term_state=EXCLUDED.term_state, "
            "im_state=EXCLUDED.im_state, "
            "flow_state=EXCLUDED.flow_state, "
            "vrp_state=EXCLUDED.vrp_state, "
            "consistency_tier=EXCLUDED.consistency_tier, "
            "cluster_coverage_ok=EXCLUDED.cluster_coverage_ok, "
            "term_classification=EXCLUDED.term_classification, "
            "skew_25d_zscore_180d=EXCLUDED.skew_25d_zscore_180d, "
            "iv_atm_30d=EXCLUDED.iv_atm_30d, "
            "rv_30d=EXCLUDED.rv_30d, "
            "vrp=EXCLUDED.vrp, "
            "vrp_zscore_60d=EXCLUDED.vrp_zscore_60d, "
            "implied_move_pct=EXCLUDED.implied_move_pct, "
            "front_iv=EXCLUDED.front_iv, "
            "back_iv=EXCLUDED.back_iv, "
            "front_back_spread=EXCLUDED.front_back_spread, "
            "pin_distance_sigma=EXCLUDED.pin_distance_sigma, "
            "vrp_sign_flip_status=EXCLUDED.vrp_sign_flip_status, "
            "vrp_sign_flip_aligned_days=EXCLUDED.vrp_sign_flip_aligned_days, "
            "vanna_conditional_reading=EXCLUDED.vanna_conditional_reading, "
            "directional_imbalance_3d=EXCLUDED.directional_imbalance_3d, "
            "vanna_oi_change_bias=EXCLUDED.vanna_oi_change_bias, "
            "charm_regime=EXCLUDED.charm_regime, "
            "charm_stress_override=EXCLUDED.charm_stress_override, "
            "skew_25d_5d_change=EXCLUDED.skew_25d_5d_change, "
            "skew_regime=EXCLUDED.skew_regime, "
            "skew_term_structure=EXCLUDED.skew_term_structure, "
            "single_point_bump_pct=EXCLUDED.single_point_bump_pct, "
            "full_curve_slope_pct=EXCLUDED.full_curve_slope_pct, "
            "term_johnson_slope_pc1=EXCLUDED.term_johnson_slope_pc1, "
            "atm_straddle_mid=EXCLUDED.atm_straddle_mid, "
            "implied_move_expected_abs=EXCLUDED.implied_move_expected_abs, "
            "implied_move_event_percentile=EXCLUDED.implied_move_event_percentile, "
            "vrp_zscore_252d=EXCLUDED.vrp_zscore_252d, "
            "generated_at=now(), inserted_at=now()"
        )
        with self._conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    state.ticker,
                    state.market_date,
                    state.threshold_version,
                    state.vanna_state,
                    state.charm_state,
                    state.skew_state,
                    state.term_state,
                    state.im_state,
                    state.flow_state,
                    state.vrp_state,
                    state.consistency_tier,
                    state.cluster_coverage_ok,
                    state.term_classification,
                    state.skew_25d_zscore_180d,
                    state.iv_atm_30d,
                    state.rv_30d,
                    state.vrp,
                    state.vrp_zscore_60d,
                    state.implied_move_pct,
                    state.front_iv,
                    state.back_iv,
                    state.front_back_spread,
                    state.pin_distance_sigma,
                    _vrp_sign_flip_status_for_db(state.vrp_sign_flip_status),
                    state.vrp_sign_flip_aligned_days,
                    state.vanna_conditional_reading,
                    state.directional_imbalance_3d,
                    state.vanna_oi_change_bias,
                    state.charm_regime,
                    state.charm_stress_override,
                    state.skew_25d_5d_change,
                    state.skew_regime,
                    state.skew_term_structure,
                    state.single_point_bump_pct,
                    state.full_curve_slope_pct,
                    state.term_johnson_slope_pc1,
                    state.atm_straddle_mid,
                    state.implied_move_expected_abs,
                    state.implied_move_event_percentile,
                    state.vrp_zscore_252d,
                ),
            )

    def fetch_matrix_state_snapshot(
        self, *, ticker: str, market_date: _date
    ) -> models.MatrixState | None:
        sql = (
            "SELECT ticker, market_date, threshold_version, vanna_state, charm_state, skew_state, "
            "term_state, im_state, flow_state, vrp_state, consistency_tier, "
            "cluster_coverage_ok, term_classification, skew_25d_zscore_180d, "
            "iv_atm_30d, rv_30d, vrp, vrp_zscore_60d, implied_move_pct, "
            "front_iv, back_iv, front_back_spread, pin_distance_sigma, vrp_sign_flip_status, "
            "vrp_sign_flip_aligned_days, vanna_conditional_reading, "
            "directional_imbalance_3d, vanna_oi_change_bias, charm_regime, "
            "charm_stress_override, skew_25d_5d_change, skew_regime, "
            "skew_term_structure, single_point_bump_pct, full_curve_slope_pct, "
            "term_johnson_slope_pc1, atm_straddle_mid, implied_move_expected_abs, "
            "implied_move_event_percentile, vrp_zscore_252d "
            f"FROM {self._schema}.matrix_state_snapshots "
            "WHERE ticker = %s AND market_date = %s"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker, market_date))
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d.name for d in cur.description or []]
            data = dict(zip(cols, row, strict=False))
            data["vrp_sign_flip_status"] = _vrp_sign_flip_status_from_db(
                data.get("vrp_sign_flip_status")
            )
            data["vrp_sign_flip_aligned_days"] = (
                data.get("vrp_sign_flip_aligned_days") or 0
            )
            return models.MatrixState(**data)

    def fetch_latest_matrix_state_snapshot(
        self, *, ticker: str
    ) -> models.MatrixState | None:
        sql = (
            "SELECT ticker, market_date, threshold_version, vanna_state, charm_state, skew_state, "
            "term_state, im_state, flow_state, vrp_state, consistency_tier, "
            "cluster_coverage_ok, term_classification, skew_25d_zscore_180d, "
            "iv_atm_30d, rv_30d, vrp, vrp_zscore_60d, implied_move_pct, "
            "front_iv, back_iv, front_back_spread, pin_distance_sigma, vrp_sign_flip_status, "
            "vrp_sign_flip_aligned_days, vanna_conditional_reading, "
            "directional_imbalance_3d, vanna_oi_change_bias, charm_regime, "
            "charm_stress_override, skew_25d_5d_change, skew_regime, "
            "skew_term_structure, single_point_bump_pct, full_curve_slope_pct, "
            "term_johnson_slope_pc1, atm_straddle_mid, implied_move_expected_abs, "
            "implied_move_event_percentile, vrp_zscore_252d "
            f"FROM {self._schema}.matrix_state_snapshots "
            "WHERE ticker = %s ORDER BY market_date DESC LIMIT 1"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker,))
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d.name for d in cur.description or []]
            data = dict(zip(cols, row, strict=False))
            data["vrp_sign_flip_status"] = _vrp_sign_flip_status_from_db(
                data.get("vrp_sign_flip_status")
            )
            data["vrp_sign_flip_aligned_days"] = (
                data.get("vrp_sign_flip_aligned_days") or 0
            )
            return models.MatrixState(**data)

    def fetch_matrix_source_freshness(
        self, *, ticker: str, market_date: _date
    ) -> models.MatrixSourceFreshness:
        return models.MatrixSourceFreshness(
            vanna_charm=self._latest_inserted_at(
                "greeks_by_expiry_strike",
                ticker=ticker,
                date_column="market_date",
                market_date=market_date,
            ),
            skew=self._latest_inserted_at(
                "risk_reversal_skew_history",
                ticker=ticker,
                date_column="market_date",
                market_date=market_date,
            ),
            term=self._latest_inserted_at(
                "iv_term_snapshots",
                ticker=ticker,
                date_column="market_date",
                market_date=market_date,
            ),
            im_vrp=self._latest_inserted_at(
                "interpolated_iv_snapshots",
                ticker=ticker,
                date_column="market_date",
                market_date=market_date,
            ),
            vrp_rv=self._latest_inserted_at(
                "realized_volatility_history",
                ticker=ticker,
                date_column="market_date",
                market_date=market_date,
            ),
            oi=self._latest_inserted_at(
                "option_chain_per_strike",
                ticker=ticker,
                date_column="snapshot_date",
                market_date=market_date,
                timestamp_column="fetched_at",
                comparison="<=",
            ),
        )

    def fetch_latest_cockpit_source_market_date(self, *, ticker: str) -> _date | None:
        sql = (
            "SELECT max(market_date) FROM ("
            f"  SELECT market_date FROM {self._schema}.greeks_by_expiry_strike "
            "  WHERE ticker = %s "
            "  UNION ALL "
            f"  SELECT market_date FROM {self._schema}.exposures_by_expiry_strike "
            "  WHERE ticker = %s "
            "  UNION ALL "
            f"  SELECT market_date FROM {self._schema}.risk_reversal_skew_history "
            "  WHERE ticker = %s "
            "  UNION ALL "
            f"  SELECT market_date FROM {self._schema}.iv_term_snapshots "
            "  WHERE ticker = %s "
            "  UNION ALL "
            f"  SELECT market_date FROM {self._schema}.interpolated_iv_snapshots "
            "  WHERE ticker = %s "
            "  UNION ALL "
            f"  SELECT market_date FROM {self._schema}.realized_volatility_history "
            "  WHERE ticker = %s "
            "  UNION ALL "
            f"  SELECT market_date FROM {self._schema}.vanna_signals "
            "  WHERE ticker = %s "
            "  UNION ALL "
            f"  SELECT market_date FROM {self._schema}.charm_signals "
            "  WHERE ticker = %s"
            ") source_dates"
        )
        with self._conn.cursor() as cur:
            cur.execute(
                sql,
                (ticker, ticker, ticker, ticker, ticker, ticker, ticker, ticker),
            )
            row = cur.fetchone()
            return row[0] if row else None

    def _latest_inserted_at(
        self,
        table: str,
        *,
        ticker: str,
        date_column: str,
        market_date: _date,
        timestamp_column: str = "inserted_at",
        comparison: str = "=",
    ) -> datetime | None:
        allowed = {
            "greeks_by_expiry_strike",
            "risk_reversal_skew_history",
            "iv_term_snapshots",
            "interpolated_iv_snapshots",
            "realized_volatility_history",
            "option_chain_per_strike",
        }
        if (
            table not in allowed
            or comparison not in {"=", "<="}
            or date_column not in {"market_date", "snapshot_date"}
            or timestamp_column not in {"inserted_at", "fetched_at"}
        ):
            raise ValueError(f"unsupported matrix freshness source: {table}")
        with self._conn.cursor() as cur:
            cur.execute(
                psql.SQL(
                    "SELECT max({}) FROM {} WHERE ticker = %s AND {} "
                    + comparison
                    + " %s"
                ).format(
                    psql.Identifier(timestamp_column),
                    psql.Identifier(self._schema, table),
                    psql.Identifier(date_column),
                ),
                (ticker, market_date),
            )
            row = cur.fetchone()
            return row[0] if row else None

    def fetch_cockpit_dealer_points(
        self, *, ticker: str, market_date: _date
    ) -> list[models.CockpitDealerPoint]:
        greeks = self.fetch_matrix_greeks_rows(ticker=ticker, market_date=market_date)
        exposures = self.fetch_matrix_exposure_rows(
            ticker=ticker, market_date=market_date
        )
        exposure_by_key = {
            (row["expiry"], row["strike"]): row
            for row in exposures
            if row.get("expiry") is not None and row.get("strike") is not None
        }
        points: list[models.CockpitDealerPoint] = []
        for row in greeks:
            key = (row["expiry"], row["strike"])
            exposure = exposure_by_key.get(key, {})
            points.append(
                models.CockpitDealerPoint(
                    expiry=row["expiry"],
                    strike=row["strike"],
                    call_vanna=row.get("call_vanna"),
                    put_vanna=row.get("put_vanna"),
                    call_charm=row.get("call_charm"),
                    put_charm=row.get("put_charm"),
                    exposure_call_vanna=exposure.get("call_vanna"),
                    exposure_put_vanna=exposure.get("put_vanna"),
                    exposure_call_charm=exposure.get("call_charm"),
                    exposure_put_charm=exposure.get("put_charm"),
                )
            )
        return points

    def upsert_vanna_signal(self, signal: models.VannaSignal) -> None:
        sql = (
            f"INSERT INTO {self._schema}.vanna_signals ("
            "ticker, market_date, dealer_net_vanna_proxy, flow_color_lookback_3d, "
            "flow_put_premium_3d, flow_call_premium_3d, iv_30d_delta_5d, "
            "vanna_conditional_reading, directional_imbalance_3d, "
            "vanna_oi_change_bias, generated_at"
            ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, COALESCE(%s, now())) "
            "ON CONFLICT (ticker, market_date) DO UPDATE SET "
            "dealer_net_vanna_proxy=EXCLUDED.dealer_net_vanna_proxy, "
            "flow_color_lookback_3d=EXCLUDED.flow_color_lookback_3d, "
            "flow_put_premium_3d=EXCLUDED.flow_put_premium_3d, "
            "flow_call_premium_3d=EXCLUDED.flow_call_premium_3d, "
            "iv_30d_delta_5d=EXCLUDED.iv_30d_delta_5d, "
            "vanna_conditional_reading=EXCLUDED.vanna_conditional_reading, "
            "directional_imbalance_3d=EXCLUDED.directional_imbalance_3d, "
            "vanna_oi_change_bias=EXCLUDED.vanna_oi_change_bias, "
            "generated_at=EXCLUDED.generated_at, inserted_at=now()"
        )
        with self._conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    signal.ticker.upper(),
                    signal.market_date,
                    signal.dealer_net_vanna_proxy,
                    signal.flow_color_lookback_3d,
                    signal.flow_put_premium_3d,
                    signal.flow_call_premium_3d,
                    signal.iv_30d_delta_5d,
                    signal.vanna_conditional_reading,
                    signal.directional_imbalance_3d,
                    signal.vanna_oi_change_bias,
                    signal.generated_at,
                ),
            )

    def fetch_vanna_signal(
        self, *, ticker: str, market_date: _date
    ) -> models.VannaSignal | None:
        sql = (
            "SELECT ticker, market_date, dealer_net_vanna_proxy, "
            "flow_color_lookback_3d, flow_put_premium_3d, flow_call_premium_3d, "
            "iv_30d_delta_5d, vanna_conditional_reading, directional_imbalance_3d, "
            "vanna_oi_change_bias, generated_at, inserted_at "
            f"FROM {self._schema}.vanna_signals "
            "WHERE ticker = %s AND market_date = %s"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker.upper(), market_date))
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d.name for d in cur.description or []]
            return models.VannaSignal(**dict(zip(cols, row, strict=False)))

    def upsert_charm_signal(self, signal: models.CharmSignal) -> None:
        sql = (
            f"INSERT INTO {self._schema}.charm_signals ("
            "ticker, market_date, pin_candidate_strike, pin_candidate_expiry, pin_source_date, "
            "pin_distance_sigma, pin_regime_flag, dealer_net_charm_proxy, "
            "net_gamma, net_gamma_sign, gamma_regime, charm_regime, "
            "charm_stress_override, generated_at"
            ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, COALESCE(%s, now())) "
            "ON CONFLICT (ticker, market_date) DO UPDATE SET "
            "pin_candidate_strike=EXCLUDED.pin_candidate_strike, "
            "pin_candidate_expiry=EXCLUDED.pin_candidate_expiry, "
            "pin_source_date=EXCLUDED.pin_source_date, "
            "pin_distance_sigma=EXCLUDED.pin_distance_sigma, "
            "pin_regime_flag=EXCLUDED.pin_regime_flag, "
            "dealer_net_charm_proxy=EXCLUDED.dealer_net_charm_proxy, "
            "net_gamma=EXCLUDED.net_gamma, "
            "net_gamma_sign=EXCLUDED.net_gamma_sign, "
            "gamma_regime=EXCLUDED.gamma_regime, "
            "charm_regime=EXCLUDED.charm_regime, "
            "charm_stress_override=EXCLUDED.charm_stress_override, "
            "generated_at=EXCLUDED.generated_at, inserted_at=now()"
        )
        with self._conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    signal.ticker.upper(),
                    signal.market_date,
                    signal.pin_candidate_strike,
                    signal.pin_candidate_expiry,
                    signal.pin_source_date,
                    signal.pin_distance_sigma,
                    signal.pin_regime_flag,
                    signal.dealer_net_charm_proxy,
                    signal.net_gamma,
                    signal.net_gamma_sign,
                    signal.gamma_regime,
                    signal.charm_regime,
                    signal.charm_stress_override,
                    signal.generated_at,
                ),
            )

    def fetch_charm_signal(
        self, *, ticker: str, market_date: _date
    ) -> models.CharmSignal | None:
        sql = (
            "SELECT ticker, market_date, pin_candidate_strike, pin_candidate_expiry, "
            "pin_source_date, pin_distance_sigma, pin_regime_flag, dealer_net_charm_proxy, "
            "net_gamma, net_gamma_sign, gamma_regime, charm_regime, "
            "charm_stress_override, generated_at, inserted_at "
            f"FROM {self._schema}.charm_signals "
            "WHERE ticker = %s AND market_date = %s"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker.upper(), market_date))
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d.name for d in cur.description or []]
            return models.CharmSignal(**dict(zip(cols, row, strict=False)))

    def persist_cockpit_dealer_signals(
        self, *, ticker: str, market_date: _date, generated_at: datetime | None = None
    ) -> models.CockpitDealerMetrics:
        metrics = self._compute_cockpit_dealer_metrics(
            ticker=ticker, market_date=market_date
        )
        self.upsert_vanna_signal(
            models.VannaSignal(
                ticker=ticker,
                market_date=market_date,
                dealer_net_vanna_proxy=metrics.dealer_net_vanna_proxy,
                flow_color_lookback_3d=metrics.flow_color_lookback_3d,
                flow_put_premium_3d=metrics.flow_put_premium_3d,
                flow_call_premium_3d=metrics.flow_call_premium_3d,
                iv_30d_delta_5d=metrics.iv_30d_delta_5d,
                vanna_conditional_reading=metrics.vanna_conditional_reading,
                directional_imbalance_3d=metrics.directional_imbalance_3d,
                vanna_oi_change_bias=metrics.vanna_oi_change_bias,
                generated_at=generated_at,
            )
        )
        self.upsert_charm_signal(
            models.CharmSignal(
                ticker=ticker,
                market_date=market_date,
                pin_candidate_strike=metrics.pin_candidate_strike,
                pin_candidate_expiry=metrics.pin_candidate_expiry,
                pin_source_date=metrics.pin_source_date,
                pin_distance_sigma=metrics.pin_distance_sigma,
                pin_regime_flag=metrics.pin_regime_flag,
                dealer_net_charm_proxy=metrics.dealer_net_charm_proxy,
                net_gamma=metrics.net_gamma,
                net_gamma_sign=metrics.net_gamma_sign,
                gamma_regime=metrics.gamma_regime,
                charm_regime=metrics.charm_regime,
                charm_stress_override=metrics.charm_stress_override,
                generated_at=generated_at,
            )
        )
        return metrics

    def fetch_cockpit_dealer_metrics(
        self, *, ticker: str, market_date: _date
    ) -> models.CockpitDealerMetrics:
        vanna = self.fetch_vanna_signal(ticker=ticker, market_date=market_date)
        charm = self.fetch_charm_signal(ticker=ticker, market_date=market_date)
        computed = self._compute_cockpit_dealer_metrics(
            ticker=ticker, market_date=market_date
        )
        return models.CockpitDealerMetrics(
            pin_candidate_strike=(
                charm.pin_candidate_strike
                if charm is not None and charm.pin_candidate_strike is not None
                else computed.pin_candidate_strike
            ),
            pin_candidate_expiry=(
                charm.pin_candidate_expiry
                if charm is not None and charm.pin_candidate_expiry is not None
                else computed.pin_candidate_expiry
            ),
            pin_source_date=(
                charm.pin_source_date
                if charm is not None and charm.pin_source_date is not None
                else computed.pin_source_date
            ),
            pin_distance_sigma=(
                charm.pin_distance_sigma
                if charm is not None and charm.pin_distance_sigma is not None
                else computed.pin_distance_sigma
            ),
            pin_regime_flag=(
                charm.pin_regime_flag
                if charm is not None and charm.pin_regime_flag is not None
                else computed.pin_regime_flag
            ),
            dealer_net_vanna_proxy=(
                vanna.dealer_net_vanna_proxy
                if vanna is not None and vanna.dealer_net_vanna_proxy is not None
                else computed.dealer_net_vanna_proxy
            ),
            dealer_net_charm_proxy=(
                charm.dealer_net_charm_proxy
                if charm is not None and charm.dealer_net_charm_proxy is not None
                else computed.dealer_net_charm_proxy
            ),
            flow_color_lookback_3d=(
                vanna.flow_color_lookback_3d
                if vanna is not None and vanna.flow_color_lookback_3d is not None
                else computed.flow_color_lookback_3d
            ),
            flow_put_premium_3d=(
                vanna.flow_put_premium_3d
                if vanna is not None and vanna.flow_put_premium_3d is not None
                else computed.flow_put_premium_3d
            ),
            flow_call_premium_3d=(
                vanna.flow_call_premium_3d
                if vanna is not None and vanna.flow_call_premium_3d is not None
                else computed.flow_call_premium_3d
            ),
            iv_30d_delta_5d=(
                vanna.iv_30d_delta_5d
                if vanna is not None and vanna.iv_30d_delta_5d is not None
                else computed.iv_30d_delta_5d
            ),
            net_gamma=(
                charm.net_gamma
                if charm is not None and charm.net_gamma is not None
                else computed.net_gamma
            ),
            net_gamma_sign=(
                charm.net_gamma_sign
                if charm is not None and charm.net_gamma_sign is not None
                else computed.net_gamma_sign
            ),
            gamma_regime=(
                charm.gamma_regime
                if charm is not None and charm.gamma_regime is not None
                else computed.gamma_regime
            ),
            vanna_conditional_reading=(
                vanna.vanna_conditional_reading
                if vanna is not None and vanna.vanna_conditional_reading is not None
                else computed.vanna_conditional_reading
            ),
            directional_imbalance_3d=(
                vanna.directional_imbalance_3d
                if vanna is not None and vanna.directional_imbalance_3d is not None
                else computed.directional_imbalance_3d
            ),
            vanna_oi_change_bias=(
                vanna.vanna_oi_change_bias
                if vanna is not None and vanna.vanna_oi_change_bias is not None
                else computed.vanna_oi_change_bias
            ),
            charm_regime=(
                charm.charm_regime
                if charm is not None and charm.charm_regime is not None
                else computed.charm_regime
            ),
            charm_stress_override=(
                charm.charm_stress_override
                if charm is not None and charm.charm_stress_override is not None
                else computed.charm_stress_override
            ),
        )

    def _compute_cockpit_dealer_metrics(
        self, *, ticker: str, market_date: _date
    ) -> models.CockpitDealerMetrics:
        greeks = self.fetch_matrix_greeks_rows(ticker=ticker, market_date=market_date)
        exposures = self.fetch_matrix_exposure_rows(
            ticker=ticker, market_date=market_date
        )
        chain_rows = self.fetch_matrix_option_chain_rows(
            ticker=ticker, market_date=market_date
        )
        pin_source_date = max(
            (
                row["snapshot_date"]
                for row in chain_rows
                if row.get("snapshot_date") is not None
            ),
            default=None,
        )
        iv_rows = self.fetch_matrix_interpolated_iv_history(
            ticker=ticker, market_date=market_date, days=10
        )
        rv_rows = self.fetch_matrix_realized_vol_history(
            ticker=ticker, market_date=market_date, days=10
        )
        flow = self._flow_color_lookback(ticker=ticker, market_date=market_date)

        chain_by_key = {
            (row["expiry"], row["strike"]): row
            for row in chain_rows
            if row.get("expiry") is not None and row.get("strike") is not None
        }
        dealer_net_vanna = Decimal(0)
        dealer_net_charm = Decimal(0)
        vanna_seen = False
        charm_seen = False
        for row in greeks:
            key = (row.get("expiry"), row.get("strike"))
            chain = chain_by_key.get(key)
            if chain is None:
                continue
            call_oi = Decimal(chain.get("call_oi") or 0)
            put_oi = Decimal(chain.get("put_oi") or 0)
            if row.get("call_vanna") is not None or row.get("put_vanna") is not None:
                dealer_net_vanna += (
                    (row.get("call_vanna") or Decimal(0)) * call_oi
                    - (row.get("put_vanna") or Decimal(0)) * put_oi
                ) * Decimal(100)
                vanna_seen = True
            expiry = row.get("expiry")
            near_expiry = expiry is not None and 0 <= (expiry - market_date).days <= 5
            if near_expiry and (
                row.get("call_charm") is not None or row.get("put_charm") is not None
            ):
                dealer_net_charm += (
                    (row.get("call_charm") or Decimal(0)) * call_oi
                    - (row.get("put_charm") or Decimal(0)) * put_oi
                ) * Decimal(100)
                charm_seen = True

        if not vanna_seen:
            exposure_vanna = _sum_optional(
                (row.get("call_vanna") or Decimal(0))
                + (row.get("put_vanna") or Decimal(0))
                for row in exposures
                if row.get("call_vanna") is not None or row.get("put_vanna") is not None
            )
            if exposure_vanna is not None:
                dealer_net_vanna = exposure_vanna
                vanna_seen = True

        if not charm_seen:
            exposure_charm = _sum_optional(
                (row.get("call_charm") or Decimal(0))
                + (row.get("put_charm") or Decimal(0))
                for row in exposures
                if row.get("expiry") is not None
                and 0 <= (row["expiry"] - market_date).days <= 5
                and (
                    row.get("call_charm") is not None
                    or row.get("put_charm") is not None
                )
            )
            if exposure_charm is not None:
                dealer_net_charm = exposure_charm
                charm_seen = True

        spot = _row_for_date(rv_rows, market_date)
        spot_price = None if spot is None else spot.get("price")
        current_iv = _row_for_date(iv_rows, market_date)
        iv_30d = None if current_iv is None else current_iv.get("volatility")
        iv_30d_delta_5d = _iv_delta_5d(iv_rows=iv_rows, market_date=market_date)
        pin = _pin_candidate(
            chain_rows=chain_rows, spot=spot_price, market_date=market_date
        )
        pin_distance_sigma = (
            _pin_distance_sigma(
                spot=spot_price,
                strike=pin[1] if pin is not None else None,
                iv_30d=iv_30d,
                dte_days=(pin[0] - market_date).days if pin is not None else None,
            )
            if pin is not None
            else None
        )
        iv_median_90d = _median(
            [
                row.get("volatility")
                for row in self.fetch_matrix_interpolated_iv_history(
                    ticker=ticker, market_date=market_date, days=90
                )
                if row.get("volatility") is not None
            ]
        )
        pin_regime = (
            iv_30d is not None
            and iv_median_90d is not None
            and pin_distance_sigma is not None
            and pin is not None
            and (pin[0] - market_date).days <= 5
            and abs(pin_distance_sigma) < Decimal("1.0")
            and iv_30d < iv_median_90d
        )
        charm_stress_override = bool(
            iv_30d is not None
            and iv_median_90d is not None
            and pin_distance_sigma is not None
            and iv_30d > iv_median_90d
            and abs(pin_distance_sigma) >= Decimal("1.0")
        )
        net_gamma = _sum_optional(
            (row.get("call_gex") or Decimal(0)) + (row.get("put_gex") or Decimal(0))
            for row in exposures
            if row.get("call_gex") is not None or row.get("put_gex") is not None
        )
        gamma_sign = _sign_label(net_gamma)
        charm_regime = _charm_regime(
            pin_regime=pin_regime if pin is not None else None,
            stress_override=charm_stress_override,
            pin_distance_sigma=pin_distance_sigma,
            pin_dte=(pin[0] - market_date).days if pin is not None else None,
        )
        vanna_reading = _vanna_conditional_reading(
            iv_30d_delta_5d=iv_30d_delta_5d,
            directional_imbalance_3d=flow["directional_imbalance"],
            flow_color=flow["color"],
            net_gamma_sign=gamma_sign,
        )

        return models.CockpitDealerMetrics(
            pin_candidate_strike=pin[1] if pin is not None else None,
            pin_candidate_expiry=pin[0] if pin is not None else None,
            pin_source_date=pin_source_date,
            pin_distance_sigma=pin_distance_sigma,
            pin_regime_flag=pin_regime if pin is not None else None,
            dealer_net_vanna_proxy=dealer_net_vanna if vanna_seen else None,
            dealer_net_charm_proxy=dealer_net_charm if charm_seen else None,
            flow_color_lookback_3d=flow["color"],
            flow_put_premium_3d=flow["put_premium"],
            flow_call_premium_3d=flow["call_premium"],
            iv_30d_delta_5d=iv_30d_delta_5d,
            net_gamma=net_gamma,
            net_gamma_sign=gamma_sign,
            gamma_regime=(
                "long_gamma"
                if gamma_sign == "positive"
                else "short_gamma"
                if gamma_sign == "negative"
                else "neutral"
                if gamma_sign == "neutral"
                else None
            ),
            vanna_conditional_reading=vanna_reading,
            directional_imbalance_3d=flow["directional_imbalance"],
            vanna_oi_change_bias=_oi_change_bias(
                self.fetch_matrix_oi_change_rows(ticker=ticker, market_date=market_date)
            ),
            charm_regime=charm_regime,
            charm_stress_override=charm_stress_override,
        )

    def _flow_color_lookback(
        self, *, ticker: str, market_date: _date, days: int = 3
    ) -> dict[str, Any]:
        sql = (
            "WITH lookback_dates AS ("
            "  SELECT DISTINCT created_at::date AS event_date "
            f"  FROM {self._schema}.flow_events "
            "  WHERE ticker = %s "
            "    AND created_at::date <= %s "
            "  ORDER BY event_date DESC "
            "  LIMIT %s"
            ") "
            "SELECT option_type, "
            "COALESCE(sum(total_premium), 0), "
            "COALESCE(sum(total_ask_side_prem), 0), "
            "COALESCE(sum(total_bid_side_prem), 0) "
            f"FROM {self._schema}.flow_events "
            "WHERE ticker = %s "
            "  AND created_at::date IN (SELECT event_date FROM lookback_dates) "
            "GROUP BY option_type"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker.upper(), market_date, days, ticker.upper()))
            rows = cur.fetchall()
        call_premium = Decimal(0)
        put_premium = Decimal(0)
        call_net = Decimal(0)
        put_net = Decimal(0)
        for option_type, premium, ask_premium, bid_premium in rows:
            premium = premium or Decimal(0)
            ask_premium = ask_premium or Decimal(0)
            bid_premium = bid_premium or Decimal(0)
            net_side = (
                ask_premium - bid_premium
                if ask_premium != 0 or bid_premium != 0
                else premium
            )
            if option_type == "call":
                call_premium += premium
                call_net += net_side
            elif option_type == "put":
                put_premium += premium
                put_net += net_side
        if not rows:
            color = None
        elif put_premium > call_premium:
            color = "put_heavy"
        elif call_premium > put_premium:
            color = "call_heavy"
        else:
            color = "neutral"
        return {
            "color": color,
            "put_premium": put_premium if rows else None,
            "call_premium": call_premium if rows else None,
            "directional_imbalance": call_net - put_net if rows else None,
        }

    def fetch_cockpit_surface(
        self, *, ticker: str, market_date: _date
    ) -> tuple[list[models.CockpitSkewPoint], list[models.CockpitTermPoint]]:
        skew_rows = self.fetch_matrix_skew_history(
            ticker=ticker, market_date=market_date
        )
        term_rows = self.fetch_matrix_term_rows(ticker=ticker, market_date=market_date)
        skew = [
            models.CockpitSkewPoint(
                market_date=row["market_date"],
                expiry=row.get("expiry"),
                risk_reversal=row.get("risk_reversal"),
            )
            for row in skew_rows
        ]
        term = [
            models.CockpitTermPoint(
                expiry=row["expiry"],
                dte=row.get("dte"),
                volatility=row.get("volatility"),
                implied_move_perc=row.get("implied_move_perc"),
                implied_move_expected_abs=(
                    Decimal(str(row["implied_move_perc"])) * Decimal("0.7979")
                    if row.get("implied_move_perc") is not None
                    else None
                ),
            )
            for row in term_rows
        ]
        return skew, term

    def fetch_cockpit_flow_alerts(
        self, *, ticker: str, limit: int = 25
    ) -> list[models.CockpitFlowAlert]:
        sql = (
            f"SELECT alert_id, ticker, option_chain, expiry, strike, option_type, "
            "total_premium, total_ask_side_prem, total_bid_side_prem, "
            "volume, open_interest, has_sweep, has_floor, has_multileg, "
            "all_opening_trades, alert_rule, flow_footprint_label, "
            "aggressor_label_confidence, created_at "
            f"FROM {self._schema}.flow_events "
            "WHERE ticker = %s "
            "ORDER BY created_at DESC NULLS LAST, total_premium DESC NULLS LAST "
            "LIMIT %s"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker.upper(), limit))
            cols = [d.name for d in cur.description or []]
            rows = [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]
        return [
            models.CockpitFlowAlert(
                alert_id=str(row["alert_id"]),
                option_chain=row.get("option_chain"),
                expiry=row.get("expiry"),
                strike=row.get("strike"),
                option_type=row.get("option_type"),
                total_premium=row.get("total_premium"),
                volume=row.get("volume"),
                open_interest=row.get("open_interest"),
                total_ask_side_prem=row.get("total_ask_side_prem"),
                total_bid_side_prem=row.get("total_bid_side_prem"),
                has_sweep=row.get("has_sweep"),
                has_floor=row.get("has_floor"),
                has_multileg=row.get("has_multileg"),
                all_opening_trades=row.get("all_opening_trades"),
                alert_rule=row.get("alert_rule"),
                flow_footprint_label=row.get("flow_footprint_label"),
                aggressor_label_confidence=row.get("aggressor_label_confidence"),
                created_at=row.get("created_at"),
            )
            for row in rows
        ]

    def fetch_cockpit_implied_moves(
        self, *, ticker: str, market_date: _date, days: int = 90
    ) -> list[models.CockpitImPoint]:
        rows = self.fetch_matrix_interpolated_iv_history(
            ticker=ticker, market_date=market_date, days=days
        )
        return [
            models.CockpitImPoint(
                market_date=row["market_date"],
                days=row["days"],
                volatility=row.get("volatility"),
                implied_move_perc=row.get("implied_move_perc"),
                implied_move_expected_abs=(
                    Decimal(str(row["implied_move_perc"])) * Decimal("0.7979")
                    if row.get("implied_move_perc") is not None
                    else None
                ),
                percentile=row.get("percentile"),
            )
            for row in rows
        ]

    def fetch_cockpit_vrp_points(
        self, *, ticker: str, market_date: _date, days: int = 90
    ) -> list[models.CockpitVrpPoint]:
        rv_rows = self.fetch_matrix_realized_vol_history(
            ticker=ticker, market_date=market_date, days=days
        )
        iv_rank_rows = self.fetch_iv_rank_history(
            ticker=ticker, market_date=market_date, days=days
        )
        iv_rank_by_date = {
            row["market_date"]: row.get("iv_rank_1y") for row in iv_rank_rows
        }
        return [
            models.CockpitVrpPoint(
                market_date=row["market_date"],
                iv=row.get("implied_volatility"),
                rv=row.get("realized_volatility"),
                vrp=(
                    row.get("implied_volatility") - row.get("realized_volatility")
                    if row.get("implied_volatility") is not None
                    and row.get("realized_volatility") is not None
                    else None
                ),
                iv_rank_1y=iv_rank_by_date.get(row["market_date"]),
            )
            for row in rv_rows
        ]

    def fetch_iv_rank_history(
        self, *, ticker: str, market_date: _date, days: int = 90
    ) -> list[dict[str, Any]]:
        sql = (
            f"SELECT market_date, close, volatility, iv_rank_1y, updated_at_src "
            f"FROM {self._schema}.iv_rank_history "
            "WHERE ticker = %s "
            "  AND market_date <= %s "
            "  AND market_date >= (%s::date - (%s || ' days')::interval) "
            "ORDER BY market_date ASC"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker, market_date, market_date, days))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

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
                WatchlistCardRow.from_list_row(row, cur.description)
                for row in cur.fetchall()
            ]

    def list_watchlist_cards_with_queue_summary(
        self,
    ) -> tuple[list[WatchlistCardRow], RescanQueueSummaryRow]:
        """Variant of list_watchlist_cards that also returns the rescan queue
        summary in a single round trip. Used by /api/watchlist to collapse
        2 DB queries into 1 in the common path.

        Edge case: when the watchlist is empty, CROSS JOIN summary drops all
        rows even if jobs exist — fall back to standalone summary query to
        preserve today's behavior (1 query in steady state, 2 in the
        empty-watchlist edge case).
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
                summary AS (
                  SELECT
                    count(*)                                     AS s_total,
                    count(*) FILTER (WHERE status = 'queued')    AS s_queued,
                    count(*) FILTER (WHERE status = 'running')   AS s_running,
                    min(requested_at)                            AS s_oldest
                  FROM active_jobs
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
                  j.started_at AS active_job_started_at,
                  sm.s_total, sm.s_queued, sm.s_running, sm.s_oldest
                FROM {self._schema}.watchlist w
                LEFT JOIN {self._schema}.watchlist_card c ON w.ticker = c.ticker
                LEFT JOIN {self._schema}.scan_runs sr ON c.run_id = sr.run_id
                LEFT JOIN latest_market_caps lmc ON w.ticker = lmc.ticker
                LEFT JOIN latest_screener_sizes lss ON w.ticker = lss.ticker
                LEFT JOIN latest_etf_aum lea ON w.ticker = lea.ticker
                LEFT JOIN {self._schema}.intraday_quote q ON w.ticker = q.ticker
                LEFT JOIN active_jobs j ON w.ticker = j.ticker
                CROSS JOIN summary sm
                WHERE w.removed_at IS NULL
                ORDER BY w.pinned DESC, w.sort_rank, w.ticker
                """
            )
            all_rows = cur.fetchall()
            description = cur.description

        if not all_rows:
            # Empty watchlist: CROSS JOIN drops all rows even if active jobs
            # exist. Fall back to standalone summary to preserve today's
            # behavior (Codex review ISSUE-3 regression guard).
            return [], self.get_rescan_queue_summary()

        # The SELECT projects 37 card columns plus 4 summary columns
        # (s_total, s_queued, s_running, s_oldest). Look up by name to be
        # robust to a future hand reordering the projection.
        col_idx = {col.name: i for i, col in enumerate(description)}
        summary_col_names = {"s_total", "s_queued", "s_running", "s_oldest"}

        first = all_rows[0]
        summary = RescanQueueSummaryRow(
            total=first[col_idx["s_total"]] or 0,
            queued=first[col_idx["s_queued"]] or 0,
            running=first[col_idx["s_running"]] or 0,
            oldest_requested_at=first[col_idx["s_oldest"]],
        )

        # Strip the 4 summary columns before constructing the strict
        # WatchlistCardRow. Filter by name (not by trailing position) so a
        # future reordering of the SELECT projection doesn't silently break.
        card_positions = [
            i for i, col in enumerate(description) if col.name not in summary_col_names
        ]
        card_cols = [description[i] for i in card_positions]
        cards = [
            WatchlistCardRow.from_list_row(
                tuple(row[i] for i in card_positions),
                card_cols,
            )
            for row in all_rows
        ]
        return cards, summary

    # daily_ohlc / intraday_quote / pcr_history methods moved to _MarketDataMixin

    # jobs queue methods moved to _JobsMixin
    # etf_aum_cache methods moved to _MarketDataMixin

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
