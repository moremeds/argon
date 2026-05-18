"""External API telemetry reads and writes."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from ._helpers import _nullable_float, _nullable_int
from .rows import (
    ExternalApiBreakdownRow,
    ExternalApiRequestRow,
    ExternalApiUsageSummary,
    ThroughputSummaryRow,
)


class _ExternalApiMixin:
    _conn: psycopg.Connection
    _schema: str

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
