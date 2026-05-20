"""Pydantic response models — over-the-wire contract for the watchlist API.

Keep stable; update `openapi-typescript` regen when fields change.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# Rescan-jobs lifecycle vocabulary, shared by QueueStatus + JobStatus.
# Source of truth is the worker / repository (see repository.py mark_job_*).
QueueStatusValue = Literal["queued", "running", "done", "failed"]


class SetupBlock(BaseModel):
    type: str | None = None
    direction: str | None = None
    score: Decimal | None = None


class ReturnsBlock(BaseModel):
    """Wire shape: d1 / w1 / d30. No aliases — FastAPI would otherwise serialize
    them as JSON keys and break the frontend contract."""

    d1: Decimal | None = None
    w1: Decimal | None = None
    d30: Decimal | None = None


class GammaBlock(BaseModel):
    flip_distance: Decimal | None = None
    flip_price: Decimal | None = None
    per_1pct_move: Decimal | None = None
    max_strike: Decimal | None = None
    expiring_pct: Decimal | None = None
    expiring_date: date | None = None


class SkewBlock(BaseModel):
    rr25d_30dte: Decimal | None = None


class PositioningBlock(BaseModel):
    call_oi: int | None = None
    put_oi: int | None = None
    pcr_oi: Decimal | None = None
    pcr_vol: Decimal | None = None
    pcr_delta_30d: Decimal | None = None


class QueueStatus(BaseModel):
    job_id: str
    status: QueueStatusValue
    queue_position: int
    requested_at: datetime
    started_at: datetime | None = None


class WatchlistCard(BaseModel):
    ticker: str
    sector: str
    pinned: bool
    sort_rank: int

    spot: Decimal | None = None
    spot_quoted_at: datetime | None = None
    spot_source: str | None = None
    # Null when the ticker is in the active watchlist but no full_scan has
    # produced a card row yet — UI renders a "no data yet" placeholder.
    scanned_at: datetime | None = None

    iv_atm: Decimal | None = None
    iv_rank: Decimal | None = None
    market_cap: Decimal | None = None
    aum: Decimal | None = None

    setup: SetupBlock
    aggression_pct: Decimal | None = None
    returns: ReturnsBlock
    gamma: GammaBlock
    skew: SkewBlock
    positioning: PositioningBlock
    queue: QueueStatus | None = None


class QueueSummary(BaseModel):
    total: int = 0
    queued: int = 0
    running: int = 0
    oldest_requested_at: datetime | None = None


class WatchlistResponse(BaseModel):
    scanned_at_min: datetime | None = None
    scanned_at_max: datetime | None = None
    scheduler_lag_seconds: float | None = None
    queue: QueueSummary = Field(default_factory=QueueSummary)
    tickers: list[WatchlistCard]


class WatchlistMutation(BaseModel):
    ticker: str
    sector: str
    notes: str | None = None
    pinned: bool = False
    sort_rank: int = 0


class WatchlistPatch(BaseModel):
    sector: str | None = None
    notes: str | None = None
    pinned: bool | None = None
    sort_rank: int | None = None


class JobStatus(BaseModel):
    job_id: str
    status: QueueStatusValue
    run_id: int | None = None
    error: str | None = None
    requested_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class OhlcRow(BaseModel):
    date: date
    open: Decimal | None = None
    high: Decimal | None = None
    low: Decimal | None = None
    close: Decimal
    volume: int | None = None


# ─── GEX (regime port from xenon 2026-05-16) ─────────────────────────────


def _to_float(v):
    """Pydantic v2 before-validator: coerce string-valued numerics from UW."""
    if v is None or isinstance(v, (int, float)):
        return v
    try:
        return float(v)
    except (TypeError, ValueError) as exc:
        _ = repr(exc)  # CI Guardrail 2: coercion failures fold to None silently
        return None


class GexLevel(BaseModel):
    strike: float | None = None
    gamma: float | None = None
    distance: float | None = None
    distance_pct: float | None = None

    _coerce_floats = field_validator(
        "strike", "gamma", "distance", "distance_pct", mode="before"
    )(_to_float)


class GexLevels(BaseModel):
    gex_flip: GexLevel | None = None
    max_magnet: GexLevel | None = None
    second_magnet: GexLevel | None = None
    max_accelerator: GexLevel | None = None
    put_wall: GexLevel | None = None
    call_wall: GexLevel | None = None


class GexBucket(BaseModel):
    strike: float | None = None
    call_gex: float | None = None
    put_gex: float | None = None
    net_gex: float | None = None
    pct_from_spot: float | None = None
    tag: str | None = None

    _coerce_floats = field_validator(
        "strike", "call_gex", "put_gex", "net_gex", "pct_from_spot", mode="before"
    )(_to_float)


class GexFlipMigrationEntry(BaseModel):
    date: str
    flip: float | None = None

    _coerce_floats = field_validator("flip", mode="before")(_to_float)


class GexBias(BaseModel):
    direction: str | None = None
    reasons: list[str] = Field(default_factory=list)
    days_above_flip: int | None = None
    flip_migration: list[GexFlipMigrationEntry] = Field(default_factory=list)


class GexExpectedRange(BaseModel):
    low: float | None = None
    high: float | None = None
    iv_1d: float | None = None

    _coerce_floats = field_validator("low", "high", "iv_1d", mode="before")(_to_float)


class GexHistoryEntry(BaseModel):
    date: str
    net_gex: float | None = None
    net_dex: float | None = None
    gex_flip: float | None = None
    spot: float | None = None
    atm_iv: float | None = None
    vol_pc: float | None = None
    bias: str | None = None

    _coerce_floats = field_validator(
        "net_gex", "net_dex", "gex_flip", "spot", "atm_iv", "vol_pc", mode="before"
    )(_to_float)


class GexIvData(BaseModel):
    iv30d: float | None = None
    iv_rank: float | None = None
    hv30: float | None = None
    mq_iv30d: float | None = None
    mq_iv_rank: str | None = None
    source: str | None = None

    _coerce_floats = field_validator(
        "iv30d", "iv_rank", "hv30", "mq_iv30d", mode="before"
    )(_to_float)


class GexMqLevels(BaseModel):
    source_date: str | None = None
    spot: float | None = None
    hvl: float | None = None
    call_resistance_all: float | None = None
    call_resistance_0dte: float | None = None
    put_support_all: float | None = None
    put_support_0dte: float | None = None
    expected_high: float | None = None
    expected_low: float | None = None
    distance_to_hvl_pct: str | None = None
    iv30d: float | None = None
    hv30: float | None = None
    iv_rank: str | None = None
    top_gex_strikes: list[float] = Field(default_factory=list)

    _coerce_floats = field_validator(
        "spot",
        "hvl",
        "call_resistance_all",
        "call_resistance_0dte",
        "put_support_all",
        "put_support_0dte",
        "expected_high",
        "expected_low",
        "iv30d",
        "hv30",
        mode="before",
    )(_to_float)


class GexSourceDeltaEntry(BaseModel):
    uw: float | None = None
    mq: float | None = None
    delta: float | None = None

    _coerce_floats = field_validator("uw", "mq", "delta", mode="before")(_to_float)


class GexSourceDelta(BaseModel):
    flip_vs_hvl: GexSourceDeltaEntry | None = None
    put_wall_vs_support_all: GexSourceDeltaEntry | None = None
    put_wall_vs_support_0dte: GexSourceDeltaEntry | None = None
    call_wall_vs_resistance_all: GexSourceDeltaEntry | None = None
    call_wall_vs_resistance_0dte: GexSourceDeltaEntry | None = None


class GexResponse(BaseModel):
    scan_time: str = ""
    market_open: bool = False
    ticker: str = "SPX"
    spot: float | None = None
    close: float | None = None
    prev_close: float | None = None
    market_time: str | None = None
    tape_time: str | None = None
    spot_source: str | None = None
    day_change: float | None = None
    day_change_pct: float | None = None
    data_date: str | None = None
    net_gex: float | None = None
    net_dex: float | None = None
    atm_iv: float | None = None
    vol_pc: float | None = None
    levels: GexLevels = Field(default_factory=GexLevels)
    profile: list[GexBucket] = Field(default_factory=list)
    expected_range: GexExpectedRange = Field(default_factory=GexExpectedRange)
    bias: GexBias = Field(default_factory=GexBias)
    history: list[GexHistoryEntry] = Field(default_factory=list)
    iv: GexIvData | None = None
    mq: GexMqLevels | None = None
    source_delta: GexSourceDelta | None = None

    _coerce_floats = field_validator(
        "spot",
        "close",
        "prev_close",
        "day_change",
        "day_change_pct",
        "net_gex",
        "net_dex",
        "atm_iv",
        "vol_pc",
        mode="before",
    )(_to_float)


EMPTY_GEX_RESPONSE = GexResponse()


class VolBackdropPoint(BaseModel):
    date: date
    close: float


class VolBackdropResponse(BaseModel):
    """Vol-complex time series + VIX term-structure (regime page header strip)."""

    series: dict[str, list[VolBackdropPoint]] = Field(default_factory=dict)
    term_structure_ratio: float | None = None  # VIX / VIX3M, latest close
    term_structure_state: str | None = None  # "contango" | "backwardation"
    as_of: date | None = None


# ─── CRI (Crash Risk Indicator) ──────────────────────────────────


class CriComponents(BaseModel):
    """Four 0-25 component scores summed into the composite 0-100."""

    vix: float = 0.0
    vvix: float = 0.0
    correlation: float = 0.0
    momentum: float = 0.0


class CriBlock(BaseModel):
    score: float = 0.0
    level: Literal["LOW", "ELEVATED", "HIGH", "CRITICAL"] = "LOW"
    components: CriComponents = Field(default_factory=CriComponents)


class CtaBlock(BaseModel):
    realized_vol: float | None = None
    exposure_pct: float | None = None
    forced_reduction_pct: float | None = None
    forced_reduction: bool = False
    est_selling_bn: float | None = None
    selling_usd_b: float | None = None


class CrashTriggerConditions(BaseModel):
    spx_below_100d_ma: bool = False
    realized_vol_gt_25: bool = False
    cor1m_gt_60: bool = False


class CrashTriggerValues(BaseModel):
    realized_vol: float | None = None
    cor1m: float | None = None


class CrashTriggerBlock(BaseModel):
    fired: bool = False
    triggered: bool = False
    conditions: CrashTriggerConditions = Field(default_factory=CrashTriggerConditions)
    values: CrashTriggerValues = Field(default_factory=CrashTriggerValues)


class CriHistoryEntry(BaseModel):
    date: str
    vix: float | None = None
    vvix: float | None = None
    spy: float | None = None
    cor1m: float | None = None
    realized_vol: float | None = None
    spx_vs_ma_pct: float | None = None
    vix_5d_roc: float | None = None
    vvix_5d_roc: float | None = None
    cor1m_5d_change: float | None = None


class CriResponse(BaseModel):
    """Crash Risk Indicator snapshot (latest scan)."""

    status: Literal["ok", "empty"] = "empty"
    scan_time: str = ""
    date: str | None = None
    vix: float | None = None
    vvix: float | None = None
    spy: float | None = None
    vix_5d_roc: float | None = None
    vvix_5d_roc: float | None = None
    vvix_vix_ratio: float | None = None
    spx_100d_ma: float | None = None
    spx_distance_pct: float | None = None
    cor1m: float | None = None
    cor1m_previous_close: float | None = None
    cor1m_5d_change: float | None = None
    realized_vol: float | None = None
    vix3m: float | None = None
    vrp: float | None = None
    vix_zscore_30d: float | None = None
    vix_vix3m_ratio: float | None = None
    spx_source: Literal["SPX", "SPY"] | None = None
    cri: CriBlock = Field(default_factory=CriBlock)
    cta: CtaBlock = Field(default_factory=CtaBlock)
    crash_trigger: CrashTriggerBlock = Field(default_factory=CrashTriggerBlock)
    history: list[CriHistoryEntry] = Field(default_factory=list)
    spy_closes: list[float] = Field(default_factory=list)


EMPTY_CRI_RESPONSE = CriResponse()


class CriScanResponse(BaseModel):
    """Response body for POST /api/regime/scan."""

    status: Literal["ok", "skipped"] = "ok"
    scanner: Literal["cri"] = "cri"
    row_id: int | None = None
    reason: str | None = None


# ─── VCG (Volatility-Credit Gap) ─────────────────────────────────


class VcgAttribution(BaseModel):
    vvix_pct: float = 0.0
    vix_pct: float = 0.0
    vvix_component: float = 0.0
    vix_component: float = 0.0
    model_implied: float = 0.0


class VcgSignal(BaseModel):
    vcg: float | None = None
    vcg_adj: float | None = None
    residual: float | None = None
    beta1_vvix: float | None = None
    beta2_vix: float | None = None
    alpha: float | None = None
    vix: float = 0.0
    vvix: float = 0.0
    credit_price: float = 0.0
    credit_5d_return_pct: float = 0.0
    ro: int = 0
    edr: int = 0
    tier: int | None = None
    bounce: int = 0
    vvix_severity: Literal["extreme", "elevated", "moderate"] = "moderate"
    sign_ok: bool = True
    sign_suppressed: bool = False
    pi_panic: float = 0.0
    regime: Literal["PANIC", "TRANSITION", "DIVERGENCE"] = "DIVERGENCE"
    interpretation: Literal[
        "RISK_OFF",
        "EDR",
        "WATCH",
        "BOUNCE",
        "NORMAL",
        "SUPPRESSED",
        "PANIC",
        "INSUFFICIENT_DATA",
    ] = "NORMAL"
    attribution: VcgAttribution = Field(default_factory=VcgAttribution)


class VcgHistoryEntry(BaseModel):
    date: str
    residual: float | None = None
    vcg: float | None = None
    vcg_adj: float | None = None
    beta1: float | None = None
    beta2: float | None = None
    vix: float = 0.0
    vvix: float = 0.0
    credit: float = 0.0
    ro: int = 0
    edr: int = 0
    tier: int | None = None
    bounce: int = 0


class VcgResponse(BaseModel):
    """Volatility-Credit Gap snapshot (latest scan)."""

    status: Literal["ok", "empty"] = "empty"
    scan_time: str = ""
    date: str | None = None
    credit_proxy: str = "HYG"
    signal: VcgSignal = Field(default_factory=VcgSignal)
    history: list[VcgHistoryEntry] = Field(default_factory=list)


EMPTY_VCG_RESPONSE = VcgResponse()


class VcgScanResponse(BaseModel):
    """Response body for POST /api/regime/vcg/scan."""

    status: Literal["ok", "skipped"] = "ok"
    scanner: Literal["vcg"] = "vcg"
    proxy: str = "HYG"
    row_id: int | None = None
    reason: str | None = None
