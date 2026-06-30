"""Warm-store collection for the pipeline benchmark."""

from __future__ import annotations

from datetime import datetime, timedelta

from uw_scan.benchmark.pipeline import BenchmarkInputs
from uw_scan.config import Settings
from uw_scan.storage.repository import Repository
from uw_scan.worker.schedule_expectations import expected_market_cron_fires_between

_PROVIDER_WINDOW = timedelta(hours=1)
_SCAN_DURATION_WINDOW = timedelta(hours=24)
_RECORD_WINDOW = timedelta(hours=8)
_WORKER_FRESH_WINDOW = timedelta(minutes=5)


def build_pipeline_benchmark_inputs(
    repo: Repository,
    settings: Settings,
    *,
    now_utc: datetime,
) -> BenchmarkInputs:
    watchlist_size = repo.count_active_watchlist()
    freshness = repo.count_pipeline_scanner_freshness(now_utc=now_utc)
    provider_start = now_utc - _PROVIDER_WINDOW
    scan_start = now_utc - _SCAN_DURATION_WINDOW
    provider_usage = repo.get_external_api_usage_summary("uw", provider_start, now_utc)
    throughput = repo.get_throughput_summary("uw", provider_start, now_utc)
    scan_durations = repo.get_scan_duration_summary(scan_start, now_utc)
    queue = repo.get_rescan_queue_summary()
    latest_heartbeat = repo.get_latest_heartbeat()
    ws_state = repo.get_ws_consumer_state()
    record_ok, failing_tables = _record_health(repo, now_utc, watchlist_size, settings)
    uw_online = _online_worker_count(
        repo,
        now_utc,
        role="uw",
        expected_count=settings.uw_worker_count,
    )
    massive_online = _online_worker_count(
        repo,
        now_utc,
        role="massive",
        expected_count=settings.massive_worker_count,
    )
    last_scan = repo.get_last_full_scan_finished_at()
    next_stale_at = (
        last_scan + timedelta(hours=settings.full_scan_stale_after_hours)
        if last_scan is not None
        else None
    )
    expected_full_scans = (
        expected_market_cron_fires_between(
            settings.full_scan_crons,
            settings.rth_tz,
            start_utc=next_stale_at,
            end_utc=now_utc,
        )
        if next_stale_at is not None
        else []
    )
    latest_expected_scan = expected_full_scans[-1] if expected_full_scans else None

    return BenchmarkInputs(
        captured_at=now_utc,
        watchlist_size=watchlist_size,
        scanner_fresh_count=freshness.fresh,
        scanner_stale_count=freshness.stale,
        scanner_dead_count=freshness.dead,
        scanner_never_scanned_count=freshness.never_scanned,
        last_full_scan_age_seconds=(
            (now_utc - last_scan).total_seconds() if last_scan is not None else None
        ),
        expected_full_scan_miss_count=len(expected_full_scans),
        full_scan_expected_lag_seconds=(
            (latest_expected_scan - last_scan).total_seconds()
            if latest_expected_scan is not None and last_scan is not None
            else None
        ),
        scan_duration_avg_seconds=scan_durations.avg_seconds,
        scan_duration_p95_seconds=scan_durations.p95_seconds,
        queue_depth=queue.total,
        oldest_queue_age_seconds=(
            (now_utc - queue.oldest_requested_at).total_seconds()
            if queue.oldest_requested_at is not None
            else None
        ),
        queue_drain_rate_per_minute=throughput.queue_drain_rate_per_minute,
        uw_latency_p95_ms=provider_usage.latency_p95_ms,
        uw_http_429=throughput.http_429,
        uw_http_4xx=provider_usage.http_4xx,
        uw_http_5xx=provider_usage.http_5xx,
        requests_per_minute=throughput.requests_per_minute,
        scheduler_heartbeat_lag_seconds=(
            # Clamp: the latest heartbeat can land a hair AFTER now_utc (clock
            # race), making the lag negative — which violates the 058 CHECK
            # (>= 0) and drops the whole snapshot. The constraint is correct;
            # fix the producer.
            max(0.0, (now_utc - latest_heartbeat[1]).total_seconds())
            if latest_heartbeat is not None
            else None
        ),
        uw_worker_online_count=uw_online,
        uw_worker_expected_count=settings.uw_worker_count,
        massive_worker_online_count=massive_online,
        massive_worker_expected_count=settings.massive_worker_count,
        ws_tick_age_seconds=(
            (now_utc - ws_state.last_tick_at).total_seconds()
            if ws_state is not None and ws_state.last_tick_at is not None
            else None
        ),
        record_health_ok=record_ok,
        failing_record_tables=tuple(failing_tables),
    )


def _online_worker_count(
    repo: Repository,
    now_utc: datetime,
    *,
    role: str,
    expected_count: int,
) -> int:
    names = [f"worker:{role}:{index}" for index in range(max(0, expected_count))]
    heartbeats = repo.get_heartbeats(names)
    return sum(
        1 for beat in heartbeats.values() if now_utc - beat <= _WORKER_FRESH_WINDOW
    )


def _record_health(
    repo: Repository,
    now_utc: datetime,
    watchlist_size: int,
    settings: Settings,
) -> tuple[bool | None, list[str]]:
    rows = repo.list_record_health(
        since=now_utc - _RECORD_WINDOW,
        daily_since=now_utc
        - timedelta(hours=settings.record_health_daily_window_hours),
        expected_tickers=watchlist_size,
        min_coverage=0.9,
        tables=["watchlist_card"],
    )
    if not rows:
        return None, []
    failing = [row.table for row in rows if not row.ok]
    return not failing, failing
