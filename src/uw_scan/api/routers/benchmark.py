"""Read-only pipeline benchmark endpoints under /api/health."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from uw_scan.api.deps import get_repo, get_settings
from uw_scan.benchmark.collector import build_pipeline_benchmark_inputs
from uw_scan.benchmark.pipeline import (
    BenchmarkReason,
    BenchmarkResult,
    ComponentScores,
    build_benchmark_result,
)
from uw_scan.config import Settings
from uw_scan.storage.repository import PipelineBenchmarkSnapshotRow, Repository

router = APIRouter()

BenchmarkStatus = Literal["OK", "DEGRADED", "CRITICAL"]


class BenchmarkReasonResponse(BaseModel):
    component: str
    severity: Literal["degraded", "critical"]
    message: str
    penalty: int


class BenchmarkSubscoresResponse(BaseModel):
    freshness: int
    coverage: int
    throughput: int
    provider: int
    worker: int
    persistence: int


class BenchmarkMetricsResponse(BaseModel):
    watchlist_size: int | None = None
    scanner_fresh_count: int | None = None
    scanner_stale_count: int | None = None
    scanner_dead_count: int | None = None
    scanner_never_scanned_count: int | None = None
    last_full_scan_age_seconds: float | None = None
    scan_duration_avg_seconds: float | None = None
    scan_duration_p95_seconds: float | None = None
    queue_depth: int | None = None
    oldest_queue_age_seconds: float | None = None
    queue_drain_rate_per_minute: float | None = None
    uw_latency_p95_ms: int | None = None
    uw_http_429: int | None = None
    uw_http_4xx: int | None = None
    uw_http_5xx: int | None = None
    requests_per_minute: float | None = None
    scheduler_heartbeat_lag_seconds: float | None = None
    uw_worker_online_count: int | None = None
    uw_worker_expected_count: int | None = None
    massive_worker_online_count: int | None = None
    massive_worker_expected_count: int | None = None
    ws_tick_age_seconds: float | None = None
    record_health_ok: bool | None = None
    failing_record_tables: list[str] = Field(default_factory=list)


class BenchmarkCurrentResponse(BaseModel):
    captured_at: datetime
    score: int
    status: BenchmarkStatus
    subscores: BenchmarkSubscoresResponse
    metrics: BenchmarkMetricsResponse
    bottleneck: BenchmarkReasonResponse | None = None
    reasons: list[BenchmarkReasonResponse] = Field(default_factory=list)


class BenchmarkSnapshotResponse(BaseModel):
    id: int
    captured_at: datetime
    capture_bucket: datetime
    score: int
    status: BenchmarkStatus
    subscores: BenchmarkSubscoresResponse
    metrics: BenchmarkMetricsResponse
    details_jsonb: dict[str, Any] = Field(default_factory=dict)


class BenchmarkHistoryResponse(BaseModel):
    snapshots: list[BenchmarkSnapshotResponse] = Field(default_factory=list)


@router.get("/health/benchmark/current", response_model=BenchmarkCurrentResponse)
def current_benchmark(
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> BenchmarkCurrentResponse:
    now_utc = datetime.now(timezone.utc)
    inputs = build_pipeline_benchmark_inputs(repo, settings, now_utc=now_utc)
    result = build_benchmark_result(inputs)
    return _current_response(result)


@router.get("/health/benchmark/history", response_model=BenchmarkHistoryResponse)
def benchmark_history(
    hours: Annotated[int, Query(ge=1, le=336)] = 24,
    repo: Repository = Depends(get_repo),
) -> BenchmarkHistoryResponse:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = repo.list_pipeline_benchmark_snapshots(since=since)
    return BenchmarkHistoryResponse(snapshots=[_snapshot_response(row) for row in rows])


def _current_response(result: BenchmarkResult) -> BenchmarkCurrentResponse:
    assert result.captured_at is not None
    return BenchmarkCurrentResponse(
        captured_at=result.captured_at,
        score=result.score,
        status=result.status,
        subscores=_subscores_response(result.subscores),
        metrics=BenchmarkMetricsResponse(
            watchlist_size=result.metrics.watchlist_size,
            scanner_fresh_count=result.metrics.scanner_fresh_count,
            scanner_stale_count=result.metrics.scanner_stale_count,
            scanner_dead_count=result.metrics.scanner_dead_count,
            scanner_never_scanned_count=result.metrics.scanner_never_scanned_count,
            last_full_scan_age_seconds=result.metrics.last_full_scan_age_seconds,
            scan_duration_avg_seconds=result.metrics.scan_duration_avg_seconds,
            scan_duration_p95_seconds=result.metrics.scan_duration_p95_seconds,
            queue_depth=result.metrics.queue_depth,
            oldest_queue_age_seconds=result.metrics.oldest_queue_age_seconds,
            queue_drain_rate_per_minute=result.metrics.queue_drain_rate_per_minute,
            uw_latency_p95_ms=result.metrics.uw_latency_p95_ms,
            uw_http_429=result.metrics.uw_http_429,
            uw_http_4xx=result.metrics.uw_http_4xx,
            uw_http_5xx=result.metrics.uw_http_5xx,
            requests_per_minute=result.metrics.requests_per_minute,
            scheduler_heartbeat_lag_seconds=(
                result.metrics.scheduler_heartbeat_lag_seconds
            ),
            uw_worker_online_count=result.metrics.uw_worker_online_count,
            uw_worker_expected_count=result.metrics.uw_worker_expected_count,
            massive_worker_online_count=result.metrics.massive_worker_online_count,
            massive_worker_expected_count=result.metrics.massive_worker_expected_count,
            ws_tick_age_seconds=result.metrics.ws_tick_age_seconds,
            record_health_ok=result.metrics.record_health_ok,
            failing_record_tables=list(result.metrics.failing_record_tables),
        ),
        bottleneck=_reason_response(result.bottleneck),
        reasons=[_reason_response(reason) for reason in result.reasons],
    )


def _snapshot_response(row: PipelineBenchmarkSnapshotRow) -> BenchmarkSnapshotResponse:
    return BenchmarkSnapshotResponse(
        id=row.id,
        captured_at=row.captured_at,
        capture_bucket=row.capture_bucket,
        score=row.score,
        status=row.status,  # type: ignore[arg-type]
        subscores=BenchmarkSubscoresResponse(
            freshness=row.freshness_score,
            coverage=row.coverage_score,
            throughput=row.throughput_score,
            provider=row.provider_score,
            worker=row.worker_score,
            persistence=row.persistence_score,
        ),
        metrics=BenchmarkMetricsResponse(
            watchlist_size=row.watchlist_size,
            scanner_fresh_count=row.scanner_fresh_count,
            scanner_stale_count=row.scanner_stale_count,
            scanner_dead_count=row.scanner_dead_count,
            scanner_never_scanned_count=row.scanner_never_scanned_count,
            scan_duration_avg_seconds=_float_or_none(row.scan_duration_avg_seconds),
            scan_duration_p95_seconds=_float_or_none(row.scan_duration_p95_seconds),
            queue_depth=row.queue_depth,
            oldest_queue_age_seconds=_float_or_none(row.oldest_queue_age_seconds),
            queue_drain_rate_per_minute=_float_or_none(
                row.queue_drain_rate_per_minute
            ),
            uw_latency_p95_ms=row.uw_latency_p95_ms,
            uw_http_429=row.uw_http_429,
            uw_http_4xx=row.uw_http_4xx,
            uw_http_5xx=row.uw_http_5xx,
            requests_per_minute=_float_or_none(row.requests_per_minute),
            scheduler_heartbeat_lag_seconds=_float_or_none(
                row.scheduler_heartbeat_lag_seconds
            ),
            uw_worker_online_count=row.uw_worker_online_count,
            uw_worker_expected_count=row.uw_worker_expected_count,
            massive_worker_online_count=row.massive_worker_online_count,
            massive_worker_expected_count=row.massive_worker_expected_count,
            ws_tick_age_seconds=_float_or_none(row.ws_tick_age_seconds),
            record_health_ok=row.record_health_ok,
            failing_record_tables=row.failing_record_tables,
        ),
        details_jsonb=row.details_jsonb,
    )


def _subscores_response(scores: ComponentScores) -> BenchmarkSubscoresResponse:
    return BenchmarkSubscoresResponse(
        freshness=scores.freshness,
        coverage=scores.coverage,
        throughput=scores.throughput,
        provider=scores.provider,
        worker=scores.worker,
        persistence=scores.persistence,
    )


def _reason_response(reason: BenchmarkReason | None) -> BenchmarkReasonResponse | None:
    if reason is None:
        return None
    return BenchmarkReasonResponse(
        component=reason.component,
        severity=reason.severity,
        message=reason.message,
        penalty=reason.penalty,
    )


def _float_or_none(value: Any) -> float | None:
    return float(value) if value is not None else None
