"""Pipeline benchmark snapshot persistence."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from .rows import PipelineBenchmarkSnapshotRow, PipelineScannerFreshnessRow


class _PipelineBenchmarkMixin:
    _conn: psycopg.Connection
    _schema: str

    def insert_pipeline_benchmark_snapshot(
        self,
        *,
        captured_at: datetime,
        capture_bucket: datetime,
        score: int,
        status: str,
        freshness_score: int,
        coverage_score: int,
        throughput_score: int,
        provider_score: int,
        worker_score: int,
        persistence_score: int,
        watchlist_size: int | None = None,
        scanner_fresh_count: int | None = None,
        scanner_stale_count: int | None = None,
        scanner_dead_count: int | None = None,
        scanner_never_scanned_count: int | None = None,
        last_full_scan_age_seconds: Decimal | float | None = None,
        scan_duration_avg_seconds: Decimal | float | None = None,
        scan_duration_p95_seconds: Decimal | float | None = None,
        queue_depth: int | None = None,
        oldest_queue_age_seconds: Decimal | float | None = None,
        queue_drain_rate_per_minute: Decimal | float | None = None,
        uw_latency_p95_ms: int | None = None,
        uw_http_429: int | None = None,
        uw_http_4xx: int | None = None,
        uw_http_5xx: int | None = None,
        requests_per_minute: Decimal | float | None = None,
        scheduler_heartbeat_lag_seconds: Decimal | float | None = None,
        uw_worker_online_count: int | None = None,
        uw_worker_expected_count: int | None = None,
        massive_worker_online_count: int | None = None,
        massive_worker_expected_count: int | None = None,
        ws_tick_age_seconds: Decimal | float | None = None,
        record_health_ok: bool | None = None,
        failing_record_tables: list[str] | tuple[str, ...] | None = None,
        details_jsonb: dict[str, Any] | None = None,
    ) -> int:
        columns = _SNAPSHOT_COLUMNS[1:]
        values = (
            captured_at,
            capture_bucket,
            score,
            status,
            freshness_score,
            coverage_score,
            throughput_score,
            provider_score,
            worker_score,
            persistence_score,
            watchlist_size,
            scanner_fresh_count,
            scanner_stale_count,
            scanner_dead_count,
            scanner_never_scanned_count,
            last_full_scan_age_seconds,
            scan_duration_avg_seconds,
            scan_duration_p95_seconds,
            queue_depth,
            oldest_queue_age_seconds,
            queue_drain_rate_per_minute,
            uw_latency_p95_ms,
            uw_http_429,
            uw_http_4xx,
            uw_http_5xx,
            requests_per_minute,
            scheduler_heartbeat_lag_seconds,
            uw_worker_online_count,
            uw_worker_expected_count,
            massive_worker_online_count,
            massive_worker_expected_count,
            ws_tick_age_seconds,
            record_health_ok,
            list(failing_record_tables or []),
            Jsonb(details_jsonb or {}),
        )
        placeholders = ", ".join(["%s"] * len(columns))
        column_sql = ", ".join(columns)
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {self._schema}.pipeline_benchmark_snapshots ({column_sql})
                VALUES ({placeholders})
                ON CONFLICT (capture_bucket) DO NOTHING
                RETURNING id
                """,
                values,
            )
            row = cur.fetchone()
            if row is None:
                cur.execute(
                    f"""
                    SELECT id
                    FROM {self._schema}.pipeline_benchmark_snapshots
                    WHERE capture_bucket = %s
                    """,
                    (capture_bucket,),
                )
                row = cur.fetchone()
        self._conn.commit()
        assert row is not None
        return int(row[0])

    def get_latest_pipeline_benchmark_snapshot(
        self,
    ) -> PipelineBenchmarkSnapshotRow | None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT {", ".join(_SNAPSHOT_COLUMNS)}
                FROM {self._schema}.pipeline_benchmark_snapshots
                ORDER BY captured_at DESC, id DESC
                LIMIT 1
                """
            )
            row = cur.fetchone()
        return _snapshot_from_row(row) if row is not None else None

    def list_pipeline_benchmark_snapshots(
        self, since: datetime, limit: int = 500
    ) -> list[PipelineBenchmarkSnapshotRow]:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT {", ".join(_SNAPSHOT_COLUMNS)}
                FROM {self._schema}.pipeline_benchmark_snapshots
                WHERE captured_at >= %s
                ORDER BY captured_at DESC, id DESC
                LIMIT %s
                """,
                (since, limit),
            )
            rows = cur.fetchall()
        return [_snapshot_from_row(row) for row in rows]

    def count_pipeline_scanner_freshness(
        self, *, now_utc: datetime, fresh_hours: int = 8, dead_hours: int = 72
    ) -> PipelineScannerFreshnessRow:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                WITH active AS (
                    SELECT ticker
                    FROM {self._schema}.watchlist
                    WHERE removed_at IS NULL
                ), latest AS (
                    SELECT
                        a.ticker,
                        sr.finished_at
                    FROM active a
                    LEFT JOIN LATERAL (
                        SELECT finished_at
                        FROM {self._schema}.scan_runs
                        WHERE ticker = a.ticker
                          AND status = 'ok'
                          AND finished_at IS NOT NULL
                          AND (notes IS DISTINCT FROM 'flow_data_refresh')
                          AND (notes IS DISTINCT FROM 'positioning_refresh')
                          AND (notes IS DISTINCT FROM 'intraday_refresh')
                          AND (notes IS DISTINCT FROM 'cockpit_daily_snapshot')
                          AND (notes IS NULL OR notes NOT LIKE 'gex_scan_%%')
                          AND EXISTS (
                              SELECT 1
                              FROM {self._schema}.signal_gates g
                              WHERE g.run_id = scan_runs.run_id
                          )
                        ORDER BY finished_at DESC, run_id DESC
                        LIMIT 1
                    ) sr ON TRUE
                )
                SELECT
                    COUNT(*) FILTER (
                        WHERE finished_at > %s::timestamptz - (%s * interval '1 hour')
                    )::int AS fresh,
                    COUNT(*) FILTER (
                        WHERE finished_at <= %s::timestamptz - (%s * interval '1 hour')
                          AND finished_at > %s::timestamptz - (%s * interval '1 hour')
                    )::int AS stale,
                    COUNT(*) FILTER (
                        WHERE finished_at <= %s::timestamptz - (%s * interval '1 hour')
                    )::int AS dead,
                    COUNT(*) FILTER (WHERE finished_at IS NULL)::int AS never_scanned
                FROM latest
                """,
                (
                    now_utc,
                    fresh_hours,
                    now_utc,
                    fresh_hours,
                    now_utc,
                    dead_hours,
                    now_utc,
                    dead_hours,
                ),
            )
            row = cur.fetchone()
        assert row is not None
        return PipelineScannerFreshnessRow(
            fresh=int(row[0]),
            stale=int(row[1]),
            dead=int(row[2]),
            never_scanned=int(row[3]),
        )


_SNAPSHOT_COLUMNS = (
    "id",
    "captured_at",
    "capture_bucket",
    "score",
    "status",
    "freshness_score",
    "coverage_score",
    "throughput_score",
    "provider_score",
    "worker_score",
    "persistence_score",
    "watchlist_size",
    "scanner_fresh_count",
    "scanner_stale_count",
    "scanner_dead_count",
    "scanner_never_scanned_count",
    "last_full_scan_age_seconds",
    "scan_duration_avg_seconds",
    "scan_duration_p95_seconds",
    "queue_depth",
    "oldest_queue_age_seconds",
    "queue_drain_rate_per_minute",
    "uw_latency_p95_ms",
    "uw_http_429",
    "uw_http_4xx",
    "uw_http_5xx",
    "requests_per_minute",
    "scheduler_heartbeat_lag_seconds",
    "uw_worker_online_count",
    "uw_worker_expected_count",
    "massive_worker_online_count",
    "massive_worker_expected_count",
    "ws_tick_age_seconds",
    "record_health_ok",
    "failing_record_tables",
    "details_jsonb",
)


def _snapshot_from_row(row: tuple[Any, ...]) -> PipelineBenchmarkSnapshotRow:
    return PipelineBenchmarkSnapshotRow(
        id=int(row[0]),
        captured_at=row[1],
        capture_bucket=row[2],
        score=int(row[3]),
        status=str(row[4]),
        freshness_score=int(row[5]),
        coverage_score=int(row[6]),
        throughput_score=int(row[7]),
        provider_score=int(row[8]),
        worker_score=int(row[9]),
        persistence_score=int(row[10]),
        watchlist_size=row[11],
        scanner_fresh_count=row[12],
        scanner_stale_count=row[13],
        scanner_dead_count=row[14],
        scanner_never_scanned_count=row[15],
        last_full_scan_age_seconds=row[16],
        scan_duration_avg_seconds=row[17],
        scan_duration_p95_seconds=row[18],
        queue_depth=row[19],
        oldest_queue_age_seconds=row[20],
        queue_drain_rate_per_minute=row[21],
        uw_latency_p95_ms=row[22],
        uw_http_429=row[23],
        uw_http_4xx=row[24],
        uw_http_5xx=row[25],
        requests_per_minute=row[26],
        scheduler_heartbeat_lag_seconds=row[27],
        uw_worker_online_count=row[28],
        uw_worker_expected_count=row[29],
        massive_worker_online_count=row[30],
        massive_worker_expected_count=row[31],
        ws_tick_age_seconds=row[32],
        record_health_ok=row[33],
        failing_record_tables=list(row[34] or []),
        details_jsonb=dict(row[35] or {}),
    )
