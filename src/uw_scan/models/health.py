"""/api/health response contract (moved from ``api/routers/health.py``, I-36)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from uw_scan.models._base import _preserve_public_module


class HealthFreshnessRow(BaseModel):
    """One curated table's data-date freshness (see reports/data_freshness)."""

    table_name: str
    date_col: str
    scope: str
    expected_count: int
    covered_count: int
    coverage_pct: float | None = None
    max_data_date: date | None = None
    days_stale: int | None = None
    frozen: bool
    consecutive_frozen_nights: int = 0


class HealthFreshness(BaseModel):
    """Per-table data-date freshness block surfaced on /api/health."""

    as_of: date | None = None
    frozen: list[str] = Field(default_factory=list)
    tables: list[HealthFreshnessRow] = Field(default_factory=list)
    # Tables the freshness-autoheal circuit breaker has stopped retriggering
    # (DATA_FRESHNESS_AUTOHEAL_CIRCUIT_BREAKER_NIGHTS consecutive frozen
    # nights despite repeated heal attempts) -- a genuinely unfixable block
    # (missing credential, licensed data source) that needs a human, not
    # another automatic retry.
    autoheal_circuit_broken: list[str] = Field(default_factory=list)


class HealthGapHealer(BaseModel):
    """Exact gap-healer status (distinct from freshness: 'all strict gaps
    healed?' not 'fresh enough?'). See reports/data_gap_healer."""

    latest_run_id: int | None = None
    latest_run_status: str | None = None
    latest_run_at: datetime | None = None
    healed: int = 0
    no_data: int = 0
    failed: int = 0
    skipped_budget: int = 0
    running: int = 0
    # Everything in the latest run not driven to a verdict. Includes 'running':
    # a run killed mid-flight strands its whole remainder there, so excluding it
    # made the number smallest exactly when the backlog was largest -- 63 reported
    # against 70,206 unprocessed after a deploy recreated the worker (2026-08-30).
    open_gaps: int = 0
    open_by_dataset: dict[str, int] = Field(default_factory=dict)
    last_verified_at: datetime | None = None


class JobFailureStreak(BaseModel):
    """One job's current consecutive-failure streak (see storage/ops_health)."""

    job_name: str
    consecutive: int
    last_error: str
    last_failed_at: datetime


class JobDegraded(BaseModel):
    """One job's current 'succeeded but degraded' record: the run returned
    normally but part of its work did not land (thin data, or one failed unit
    among interchangeable ones). Informational only — it never flips ``ok``,
    never sets ``reason`` and never alerts, and it self-clears on the next
    clean run or source success (see reports/health_blocks._job_degraded)."""

    #: The scheduled job id for scan-run records ("regime_grg_scan",
    #: "discovery_scan"); the ``macro_source_status.source`` key for
    #: macro-source records.
    job_name: str
    #: Which existing record the entry was read from.
    record: Literal["scan_run", "macro_source"]
    #: ``scan_runs.finished_at`` or ``macro_source_status.last_attempt_at``.
    since: datetime | None = None
    #: Human-readable summary (e.g. "dp 31/50 enriched",
    #: "error_type: error_message").
    detail: str | None = None
    #: ``macro_source_status.consecutive_failures``; None for scan runs.
    consecutive: int | None = None


class TradeInsightsAiProviderHealth(BaseModel):
    """Per-provider AI worker pool status."""

    workers_expected: int
    workers_healthy: int
    queued_depth: int
    last_beat_at: datetime | None = None


class TradeInsightsAiHealth(BaseModel):
    codex: TradeInsightsAiProviderHealth
    claude: TradeInsightsAiProviderHealth
    deepseek: TradeInsightsAiProviderHealth


class WsConsumerHealth(BaseModel):
    """Spot WS consumer status (xenon primary / massive fallback), surfaced
    for the HealthPanel.

    ``healthy`` is true when:
      * the market is closed (no ticks are expected), OR
      * ``last_flush_at`` is within ``massive_ws_heartbeat_stale_after_seconds``.

    ``active_source`` tells which feed the consumer is connected to —
    ``"xenon_ws"`` (primary) or ``"massive.com_ws"`` (fallback); ``None``
    before the first connection. ``reason`` carries the short label the UI
    displays under the row.
    """

    healthy: bool
    last_tick_at: datetime | None = None
    last_tick_age_seconds: float | None = None
    last_flush_at: datetime | None = None
    ticks_received: int = 0
    ticks_flushed: int = 0
    connection_started_at: datetime | None = None
    last_error: str | None = None
    active_source: str | None = None
    reason: str | None = None


class WorkerHealth(BaseModel):
    label: str
    role: Literal["uw", "massive", "ai"]
    index: int
    heartbeat_name: str
    lag_seconds: float | None = None
    last_beat_at: datetime | None = None


class RecordHealthCheck(BaseModel):
    table: str
    window_start: datetime
    expected_tickers: int
    expected_min_tickers: int
    actual_tickers: int
    expected_min_rows: int
    actual_rows: int
    latest_at: datetime | None = None
    ok: bool


class HealthResponse(BaseModel):
    ok: bool
    db: str
    # Running backend release version (repo-root VERSION file), e.g. "0.1.1".
    version: str
    scheduler_lag_seconds: float | None = None
    last_full_scan_at: datetime | None = None
    reason: str | None = None
    # Extra fields surfaced in the sidebar HealthPanel. Decoupled from the
    # ok/reason gating above so a benign "no scans yet" still returns lag /
    # watchlist size for the UI.
    worker_lag_seconds: float | None = None
    scheduler_heartbeat_lag_seconds: float | None = None
    scheduler_heartbeat_name: str | None = None
    rescan_heartbeat_lag_seconds: float | None = None
    # No spot_refresh_heartbeat_lag_seconds: the spot_refresh job was deleted in
    # Phase 7 (the WS consumer is the sole intraday spot writer). Nothing has
    # written that heartbeat since, so the field could only ever report "time
    # since the retired job last ran" — ~68 days and climbing by 2026-07. Live
    # spot health is spot_quote_lag_seconds plus the ws_consumer block.
    spot_quote_lag_seconds: float | None = None
    latest_spot_quote_at: datetime | None = None
    latest_spot_quote_fetched_at: datetime | None = None
    watchlist_size: int | None = None
    source: str = "UnusualWhales"
    latency_p95_ms: int | None = None
    http_2xx: int | None = None
    http_4xx: int | None = None
    http_5xx: int | None = None
    uw_today: int | None = None
    cache_hit_pct: float | None = None
    throughput_window_minutes: float = 0.0
    requests_per_minute: float | None = None
    http_429: int | None = None
    avg_scan_duration_seconds: float | None = None
    queue_drain_rate_per_minute: float | None = None
    record_health_ok: bool | None = None
    record_health: list["RecordHealthCheck"] = Field(default_factory=list)
    # Oldest computed_at among the snapshot rows served in record_health.
    record_health_computed_at: datetime | None = None
    workers: list["WorkerHealth"] = Field(default_factory=list)
    ws_consumer: "WsConsumerHealth | None" = None
    trade_insights_ai: "TradeInsightsAiHealth | None" = None
    freshness: "HealthFreshness | None" = None
    gap_healer: "HealthGapHealer | None" = None
    job_failures: list["JobFailureStreak"] = Field(default_factory=list)
    job_degraded: list["JobDegraded"] = Field(default_factory=list)


_preserve_public_module(
    HealthResponse,
    HealthFreshnessRow,
    HealthFreshness,
    HealthGapHealer,
    JobFailureStreak,
    JobDegraded,
    TradeInsightsAiProviderHealth,
    TradeInsightsAiHealth,
    WsConsumerHealth,
    WorkerHealth,
    RecordHealthCheck,
)
