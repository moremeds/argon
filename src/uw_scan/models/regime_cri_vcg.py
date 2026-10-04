"""CRI/VCG regime response models — over-the-wire contract for the regime API.

Keep stable; update `openapi-typescript` regen when fields change.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

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
    # v3 emits 3; older snapshots carry 1 after the 050 backfill migration.
    # Constrained to known enumerated versions to prevent typo'd drift.
    composite_version: Literal[1, 2, 3] | None = None
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
    # v3: needed so the UI prior-dot for the tactical Trend Break sub-score
    # can be drawn from yesterday's value.
    pullback_20d_pct: float | None = None


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
    # v3: tactical pullback in % and absolute VIX velocity in points.
    pullback_20d_pct: float | None = None
    vix_delta_3d: float | None = None
    spx_source: Literal["SPX", "SPY"] | None = None
    cri: CriBlock = Field(default_factory=CriBlock)
    cta: CtaBlock = Field(default_factory=CtaBlock)
    crash_trigger: CrashTriggerBlock = Field(default_factory=CrashTriggerBlock)
    history: list[CriHistoryEntry] = Field(default_factory=list)
    spy_closes: list[float] = Field(default_factory=list)

    @field_validator("pullback_20d_pct", "vix_delta_3d", mode="after")
    @classmethod
    def _coerce_nonfinite_to_none(cls, v: float | None) -> float | None:
        """NaN / Inf → None. Belt-and-suspenders so the API never emits the
        literal `NaN` JSON token (which is rejected by strict parsers)."""
        import math as _math

        if v is None:
            return None
        if not _math.isfinite(v):
            return None
        return v


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
    vix_percentile_rank: float | None = Field(
        default=None,
        description=(
            "VIX level's 252-day rolling percentile rank (strict_lt tie rule). "
            "Used by the v2 absolute-vol-stress override gate. None during the "
            "252-bar warmup or for v=1 payloads."
        ),
    )
    vvix_percentile_rank: float | None = Field(
        default=None,
        description=(
            "VVIX level's 252-day rolling percentile rank (strict_lt tie rule). "
            "Used by the v2 absolute-vol-stress override gate."
        ),
    )
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


# ─── Regime live (WS-quote-driven CRI/VCG) ───────────────────────


class RegimeLiveQuote(BaseModel):
    """One live WS quote echoed by the live endpoints / quotes strip."""

    price: float
    quoted_at: datetime
    source: str | None = None


class CriLiveResponse(CriResponse):
    """CRI computed at request time with live quotes spliced as today's
    provisional close. ``basis='eod'`` means the live compute wasn't
    possible (stale/no quotes) and the latest persisted EOD snapshot is
    being served instead."""

    basis: Literal["live", "eod"] = "eod"
    live_quotes: dict[str, RegimeLiveQuote] = Field(default_factory=dict)
    carried_forward: list[str] = Field(default_factory=list)
    active_source: str | None = None


class VcgLiveResponse(VcgResponse):
    basis: Literal["live", "eod"] = "eod"
    live_quotes: dict[str, RegimeLiveQuote] = Field(default_factory=dict)
    carried_forward: list[str] = Field(default_factory=list)
    active_source: str | None = None


class CriIntradayPoint(BaseModel):
    ts: datetime
    cri_score: float | None = None
    vix: float | None = None
    vvix: float | None = None
    spx: float | None = None
    cor1m: float | None = None
    vix3m: float | None = None
    realized_vol: float | None = None
    vrp: float | None = None
    vix_zscore_30d: float | None = None
    vix_vix3m_ratio: float | None = None
    spx_distance_pct: float | None = None


class CriIntradaySession(BaseModel):
    et_date: date
    points: list[CriIntradayPoint] = Field(default_factory=list)


class CriIntradayResponse(BaseModel):
    sessions: list[CriIntradaySession] = Field(default_factory=list)
    as_of: datetime | None = None


class CriDailyEntry(BaseModel):
    date: date
    cri_score: float | None = None
    vix: float | None = None
    vvix: float | None = None
    spx: float | None = None
    cor1m: float | None = None
    vix3m: float | None = None
    realized_vol: float | None = None
    vrp: float | None = None
    vix_zscore_30d: float | None = None
    vix_vix3m_ratio: float | None = None
    spx_distance_pct: float | None = None


class CriDailyHistoryResponse(BaseModel):
    rows: list[CriDailyEntry] = Field(default_factory=list)


class VcgIntradayPoint(BaseModel):
    ts: datetime
    vcg: float | None = None
    vcg_adj: float | None = None
    residual: float | None = None
    credit_price: float | None = None
    credit_5d_return_pct: float | None = None
    vix: float | None = None
    vvix: float | None = None
    beta1: float | None = None
    beta2: float | None = None


class VcgIntradaySession(BaseModel):
    et_date: date
    points: list[VcgIntradayPoint] = Field(default_factory=list)


class VcgIntradayResponse(BaseModel):
    credit_proxy: str = "HYG"
    sessions: list[VcgIntradaySession] = Field(default_factory=list)
    as_of: datetime | None = None


class VcgDailyEntry(BaseModel):
    date: date
    vcg: float | None = None
    vcg_adj: float | None = None
    residual: float | None = None
    credit_price: float | None = None
    credit_5d_return_pct: float | None = None
    vix: float | None = None
    vvix: float | None = None
    beta1: float | None = None
    beta2: float | None = None


class VcgDailyHistoryResponse(BaseModel):
    credit_proxy: str = "HYG"
    rows: list[VcgDailyEntry] = Field(default_factory=list)


class RegimeQuotesResponse(BaseModel):
    """Lightweight live-quote projection for the regime header strip."""

    quotes: dict[str, RegimeLiveQuote] = Field(default_factory=dict)
    active_source: str | None = None
    as_of: datetime | None = None
    # The server's staleness window (REGIME_LIVE_QUOTE_MAX_AGE_SECONDS) so
    # the client's "is this quote live?" check can't drift from the value
    # the live endpoints actually use.
    fresh_within_seconds: int = 900
