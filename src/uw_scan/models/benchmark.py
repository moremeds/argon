"""Pipeline benchmark response models for the /api/health endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

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
