"""Pure pipeline benchmark scoring.

This module is intentionally storage-agnostic. DB-backed collectors assemble a
``BenchmarkInputs`` instance and pass it here for deterministic scoring.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

BenchmarkStatus = Literal["OK", "DEGRADED", "CRITICAL"]
BenchmarkComponent = Literal[
    "freshness", "coverage", "throughput", "provider", "worker", "persistence"
]

_WEIGHTS: dict[BenchmarkComponent, int] = {
    "freshness": 25,
    "coverage": 20,
    "throughput": 15,
    "provider": 15,
    "worker": 15,
    "persistence": 10,
}


@dataclass(frozen=True)
class BenchmarkInputs:
    captured_at: datetime | None = None
    watchlist_size: int = 0
    scanner_fresh_count: int = 0
    scanner_stale_count: int = 0
    scanner_dead_count: int = 0
    scanner_never_scanned_count: int = 0
    last_full_scan_age_seconds: float | None = None
    expected_full_scan_miss_count: int = 0
    full_scan_expected_lag_seconds: float | None = None
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
    failing_record_tables: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ComponentScores:
    freshness: int
    coverage: int
    throughput: int
    provider: int
    worker: int
    persistence: int


@dataclass(frozen=True)
class BenchmarkReason:
    component: BenchmarkComponent
    severity: Literal["degraded", "critical"]
    message: str
    penalty: int


@dataclass(frozen=True)
class BenchmarkResult:
    captured_at: datetime | None
    score: int
    status: BenchmarkStatus
    subscores: ComponentScores
    metrics: BenchmarkInputs
    bottleneck: BenchmarkReason | None
    reasons: list[BenchmarkReason]


def classify_status(score: int) -> BenchmarkStatus:
    if score >= 85:
        return "OK"
    if score >= 60:
        return "DEGRADED"
    return "CRITICAL"


def weighted_score(scores: ComponentScores) -> int:
    raw = (
        scores.freshness * _WEIGHTS["freshness"]
        + scores.coverage * _WEIGHTS["coverage"]
        + scores.throughput * _WEIGHTS["throughput"]
        + scores.provider * _WEIGHTS["provider"]
        + scores.worker * _WEIGHTS["worker"]
        + scores.persistence * _WEIGHTS["persistence"]
    ) / sum(_WEIGHTS.values())
    return _clamp_score(raw)


def compute_component_scores(
    inputs: BenchmarkInputs,
) -> tuple[ComponentScores, list[BenchmarkReason]]:
    reasons: list[BenchmarkReason] = []
    scores = ComponentScores(
        freshness=_score_freshness(inputs, reasons),
        coverage=_score_coverage(inputs, reasons),
        throughput=_score_throughput(inputs, reasons),
        provider=_score_provider(inputs, reasons),
        worker=_score_worker(inputs, reasons),
        persistence=_score_persistence(inputs, reasons),
    )
    return scores, reasons


def build_benchmark_result(inputs: BenchmarkInputs) -> BenchmarkResult:
    scores, reasons = compute_component_scores(inputs)
    score = weighted_score(scores)
    bottleneck = max(reasons, key=lambda reason: reason.penalty, default=None)
    return BenchmarkResult(
        captured_at=inputs.captured_at,
        score=score,
        status=classify_status(score),
        subscores=scores,
        metrics=inputs,
        bottleneck=bottleneck,
        reasons=reasons,
    )


def result_details_json(result: BenchmarkResult) -> dict[str, Any]:
    return {
        "bottleneck": result.bottleneck.component if result.bottleneck else None,
        "reasons": [
            {
                "component": reason.component,
                "severity": reason.severity,
                "message": reason.message,
                "penalty": reason.penalty,
            }
            for reason in result.reasons
        ],
    }


def _score_freshness(
    inputs: BenchmarkInputs, reasons: list[BenchmarkReason]
) -> int:
    total = inputs.watchlist_size
    if total <= 0:
        _add_reason(reasons, "freshness", 50, "no active watchlist tickers")
        return 50
    freshness_score = (
        (inputs.scanner_fresh_count + inputs.scanner_stale_count * 0.35) / total
    ) * 100
    if inputs.expected_full_scan_miss_count >= 2:
        expected_lag_hours = (
            inputs.full_scan_expected_lag_seconds / 3600
            if inputs.full_scan_expected_lag_seconds is not None
            else None
        )
        lag = (
            f"; latest expected scan is {expected_lag_hours:.1f}h after last scan"
            if expected_lag_hours is not None
            else ""
        )
        if inputs.expected_full_scan_miss_count >= 6:
            freshness_score -= 45
            _add_reason(
                reasons,
                "freshness",
                45,
                f"{inputs.expected_full_scan_miss_count} expected full scans missed{lag}",
            )
        else:
            freshness_score -= 20
            _add_reason(
                reasons,
                "freshness",
                20,
                f"{inputs.expected_full_scan_miss_count} expected full scans missed{lag}",
            )
    score = _clamp_score(freshness_score)
    if score < 85:
        _add_reason(
            reasons,
            "freshness",
            100 - score,
            (
                f"{inputs.scanner_fresh_count} of {total} scanner tickers are "
                "fresh"
            ),
        )
    return score


def _score_coverage(inputs: BenchmarkInputs, reasons: list[BenchmarkReason]) -> int:
    total = inputs.watchlist_size
    if total <= 0:
        _add_reason(reasons, "coverage", 50, "no active watchlist tickers")
        return 50
    weighted_covered = (
        inputs.scanner_fresh_count
        + inputs.scanner_stale_count * 0.35
        + inputs.scanner_dead_count * 0.05
    )
    score = _clamp_score((weighted_covered / total) * 100)
    missing = inputs.scanner_dead_count + inputs.scanner_never_scanned_count
    if score < 85 or missing:
        _add_reason(
            reasons,
            "coverage",
            max(100 - score, missing),
            (
                f"{inputs.scanner_fresh_count} fresh, "
                f"{inputs.scanner_stale_count} stale, "
                f"{inputs.scanner_dead_count} dead, "
                f"{inputs.scanner_never_scanned_count} never scanned"
            ),
        )
    return score


def _score_throughput(
    inputs: BenchmarkInputs, reasons: list[BenchmarkReason]
) -> int:
    score = 100
    if inputs.scan_duration_p95_seconds is not None:
        if inputs.scan_duration_p95_seconds > 600:
            score -= 35
            _add_reason(reasons, "throughput", 35, "scan p95 exceeds 10 minutes")
        elif inputs.scan_duration_p95_seconds > 240:
            score -= 15
            _add_reason(reasons, "throughput", 15, "scan p95 exceeds 4 minutes")
    if inputs.queue_depth is not None and inputs.queue_depth > 0:
        penalty = min(35, inputs.queue_depth * 5)
        score -= penalty
        _add_reason(reasons, "throughput", penalty, f"{inputs.queue_depth} jobs queued")
    if inputs.oldest_queue_age_seconds is not None and inputs.oldest_queue_age_seconds > 900:
        score -= 20
        _add_reason(reasons, "throughput", 20, "oldest queued job exceeds 15 minutes")
    return _clamp_score(score)


def _score_provider(inputs: BenchmarkInputs, reasons: list[BenchmarkReason]) -> int:
    score = 100
    if inputs.uw_latency_p95_ms is not None:
        if inputs.uw_latency_p95_ms > 2000:
            score -= 30
            _add_reason(reasons, "provider", 30, "UW p95 latency exceeds 2s")
        elif inputs.uw_latency_p95_ms > 1000:
            score -= 15
            _add_reason(reasons, "provider", 15, "UW p95 latency exceeds 1s")
    error_count = (inputs.uw_http_429 or 0) + (inputs.uw_http_5xx or 0)
    if error_count:
        penalty = min(45, error_count * 10)
        score -= penalty
        _add_reason(reasons, "provider", penalty, f"{error_count} UW 429/5xx responses")
    if inputs.uw_http_4xx:
        penalty = min(20, inputs.uw_http_4xx * 3)
        score -= penalty
        _add_reason(reasons, "provider", penalty, f"{inputs.uw_http_4xx} UW 4xx responses")
    return _clamp_score(score)


def _score_worker(inputs: BenchmarkInputs, reasons: list[BenchmarkReason]) -> int:
    score = 100
    for label, online, expected in (
        ("UW", inputs.uw_worker_online_count, inputs.uw_worker_expected_count),
        (
            "Massive",
            inputs.massive_worker_online_count,
            inputs.massive_worker_expected_count,
        ),
    ):
        if expected is not None and expected > 0 and online is not None and online < expected:
            missing = expected - online
            penalty = min(40, missing * 20)
            score -= penalty
            _add_reason(reasons, "worker", penalty, f"{missing} {label} worker(s) offline")
    if inputs.scheduler_heartbeat_lag_seconds is not None and inputs.scheduler_heartbeat_lag_seconds > 300:
        score -= 25
        _add_reason(reasons, "worker", 25, "scheduler heartbeat exceeds 5 minutes")
    if inputs.ws_tick_age_seconds is not None and inputs.ws_tick_age_seconds > 300:
        score -= 15
        _add_reason(reasons, "worker", 15, "WS tick heartbeat exceeds 5 minutes")
    return _clamp_score(score)


def _score_persistence(
    inputs: BenchmarkInputs, reasons: list[BenchmarkReason]
) -> int:
    if inputs.record_health_ok is None:
        return 80
    if inputs.record_health_ok:
        return 100
    failing = ", ".join(inputs.failing_record_tables) or "record-health tables"
    _add_reason(
        reasons,
        "persistence",
        50,
        f"record coverage below expected for {failing}",
    )
    return 50


def _add_reason(
    reasons: list[BenchmarkReason],
    component: BenchmarkComponent,
    penalty: int,
    message: str,
) -> None:
    reasons.append(
        BenchmarkReason(
            component=component,
            severity="critical" if penalty >= 40 else "degraded",
            message=message,
            penalty=penalty,
        )
    )


def _clamp_score(value: float) -> int:
    return max(0, min(100, round(value)))
