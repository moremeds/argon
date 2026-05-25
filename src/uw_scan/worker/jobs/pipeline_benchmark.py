"""Scheduled pipeline benchmark snapshot job."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Iterator

import psycopg

from uw_scan.benchmark.collector import build_pipeline_benchmark_inputs
from uw_scan.benchmark.pipeline import build_benchmark_result, result_details_json
from uw_scan.config import Settings
from uw_scan.storage.repository import Repository

logger = logging.getLogger(__name__)

PIPELINE_BENCHMARK_LOCK_KEY = 91601
_CAPTURE_INTERVAL = timedelta(minutes=5)


def pipeline_benchmark_snapshot_job(settings: Settings | None = None) -> int:
    resolved_settings = settings or Settings.from_env()
    now_utc = datetime.now(UTC)
    with _repo(resolved_settings) as repo:
        if not repo.try_advisory_lock(PIPELINE_BENCHMARK_LOCK_KEY):
            logger.info("pipeline benchmark snapshot skipped; advisory lock busy")
            return 0
        try:
            inputs = build_pipeline_benchmark_inputs(
                repo,
                resolved_settings,
                now_utc=now_utc,
            )
            result = build_benchmark_result(inputs)
            captured_at = result.captured_at or now_utc
            snapshot_id = repo.insert_pipeline_benchmark_snapshot(
                captured_at=captured_at,
                capture_bucket=_floor_capture_bucket(captured_at),
                score=result.score,
                status=result.status,
                freshness_score=result.subscores.freshness,
                coverage_score=result.subscores.coverage,
                throughput_score=result.subscores.throughput,
                provider_score=result.subscores.provider,
                worker_score=result.subscores.worker,
                persistence_score=result.subscores.persistence,
                watchlist_size=inputs.watchlist_size,
                scanner_fresh_count=inputs.scanner_fresh_count,
                scanner_stale_count=inputs.scanner_stale_count,
                scanner_dead_count=inputs.scanner_dead_count,
                scanner_never_scanned_count=inputs.scanner_never_scanned_count,
                scan_duration_avg_seconds=inputs.scan_duration_avg_seconds,
                scan_duration_p95_seconds=inputs.scan_duration_p95_seconds,
                queue_depth=inputs.queue_depth,
                oldest_queue_age_seconds=inputs.oldest_queue_age_seconds,
                queue_drain_rate_per_minute=inputs.queue_drain_rate_per_minute,
                uw_latency_p95_ms=inputs.uw_latency_p95_ms,
                uw_http_429=inputs.uw_http_429,
                uw_http_4xx=inputs.uw_http_4xx,
                uw_http_5xx=inputs.uw_http_5xx,
                requests_per_minute=inputs.requests_per_minute,
                scheduler_heartbeat_lag_seconds=(
                    inputs.scheduler_heartbeat_lag_seconds
                ),
                uw_worker_online_count=inputs.uw_worker_online_count,
                uw_worker_expected_count=inputs.uw_worker_expected_count,
                massive_worker_online_count=inputs.massive_worker_online_count,
                massive_worker_expected_count=inputs.massive_worker_expected_count,
                ws_tick_age_seconds=inputs.ws_tick_age_seconds,
                record_health_ok=inputs.record_health_ok,
                failing_record_tables=inputs.failing_record_tables,
                details_jsonb=result_details_json(result),
            )
            logger.info("pipeline benchmark snapshot inserted id=%s", snapshot_id)
            return snapshot_id
        except Exception as exc:
            logger.exception("pipeline benchmark snapshot failed: %s", repr(exc))
            raise
        finally:
            repo.release_advisory_lock(PIPELINE_BENCHMARK_LOCK_KEY)


@contextmanager
def _repo(settings: Settings) -> Iterator[Repository]:
    conn = psycopg.connect(settings.db_dsn())
    try:
        yield Repository(conn, schema=settings.db_schema)
    finally:
        conn.close()


def _floor_capture_bucket(captured_at: datetime) -> datetime:
    epoch_seconds = int(captured_at.timestamp())
    interval_seconds = int(_CAPTURE_INTERVAL.total_seconds())
    floored = epoch_seconds - (epoch_seconds % interval_seconds)
    return datetime.fromtimestamp(floored, tz=UTC)
