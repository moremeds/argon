"""GRG (Gamma Rotation Gap) response models — over-the-wire regime contract.

Keep stable; update `openapi-typescript` regen when fields change.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# ─── GRG (Gamma Rotation Gap) ────────────────────────────────────


class GrgGate(BaseModel):
    id: str
    label: str
    status: Literal["PASS", "WATCH", "FAIL"] = "WATCH"
    copy: str = ""


class GrgAsset(BaseModel):
    ticker: str
    spot: float | None = None
    data_date: str | None = None
    net_gamma: float | None = None
    net_gex: float | None = None
    gamma_z: float | None = None
    gamma_1d_change: float | None = None
    gamma_3d_change: float | None = None
    state: Literal["CUSHION", "WHIP", "NEUTRAL"] = "NEUTRAL"
    flip: float | None = None
    spot_vs_flip_pct: float | None = None


class GrgAssets(BaseModel):
    SPY: GrgAsset
    TLT: GrgAsset


class GrgSignal(BaseModel):
    state: Literal[
        "RISK_ON_DIVERGENCE",
        "RISK_OFF_DIVERGENCE",
        "DUAL_CUSHION",
        "DUAL_WHIP",
        "NEUTRAL",
    ] = "NEUTRAL"
    state_label: str = "Neutral"
    interpretation: Literal[
        "TOP_WATCH",
        "BOTTOM_WATCH",
        "RISK_ON",
        "RISK_OFF",
        "DUAL_WHIP",
        "CUSHION",
        "NORMAL",
    ] = "NORMAL"
    tier: int | None = None
    top_watch: bool = False
    bottom_watch: bool = False
    top_score: int = 0
    bottom_score: int = 0
    grg_z: float | None = None
    raw_spread: float | None = None
    spy_gamma_z: float | None = None
    tlt_gamma_z: float | None = None
    spy_3d_gamma_change: float | None = None
    tlt_3d_gamma_change: float | None = None
    summary: str = ""


class GrgHistoryEntry(BaseModel):
    date: str
    spy_price: float | None = None
    spy_net_gamma: float | None = None
    tlt_net_gamma: float | None = None
    spy_gamma_z: float | None = None
    tlt_gamma_z: float | None = None
    grg_z: float | None = None
    raw_spread: float | None = None
    state: str | None = None


class GrgTopBottomSide(BaseModel):
    active: bool = False
    copy: str = ""


class GrgTopBottom(BaseModel):
    top: GrgTopBottomSide = Field(default_factory=GrgTopBottomSide)
    bottom: GrgTopBottomSide = Field(default_factory=GrgTopBottomSide)


class GrgEvent(BaseModel):
    """One gate-confirmed top/bottom day (YTD history of the signal).

    ``spot_vs_flip`` is deliberately absent — UW's greek-exposure history has
    no per-day gamma flip, so it can't be backfilled for past events; it lives
    on the live SPY/TLT cards only.

    ``fwd_20d_pct`` / ``lead_sessions`` / ``extreme_gap_pct`` are the YTD
    forward-return backtest: SPY's 20-session forward return after the watch,
    the sessions until the adverse price extreme it preceded, and how much
    further SPY moved to that extreme. They show the watch LEADS the turn.
    """

    date: str
    grg_z: float | None = None
    pair_state: str = "NEUTRAL"
    tier: int | None = None
    spy_net_gamma: float | None = None
    tlt_net_gamma: float | None = None
    fwd_20d_pct: float | None = None
    lead_sessions: int | None = None
    extreme_gap_pct: float | None = None


class GrgEventSideStats(BaseModel):
    n: int = 0
    median_lead_sessions: float | None = None
    median_extreme_gap_pct: float | None = None


class GrgEventStats(BaseModel):
    """Aggregate YTD forward-return backtest of the gate-confirmed watch events.

    ``median_lead_sessions`` is the median sessions between a watch signal and
    the adverse extreme it preceded; ``median_extreme_gap_pct`` is the median
    further move after the signal. Together they quantify the early-warning
    LEAD — GRG watch events are not coincident turn markers.
    """

    fwd_window: int = 0
    tops: GrgEventSideStats = Field(default_factory=GrgEventSideStats)
    bottoms: GrgEventSideStats = Field(default_factory=GrgEventSideStats)


class GrgEvents(BaseModel):
    tops: list[GrgEvent] = Field(default_factory=list)
    bottoms: list[GrgEvent] = Field(default_factory=list)
    stats: GrgEventStats = Field(default_factory=GrgEventStats)


class GrgResponse(BaseModel):
    """Gamma Rotation Gap snapshot (latest scan). Self-contained: embeds the
    YTD history (z-scored over the full ≈1Y fetched series)."""

    status: Literal["ok", "empty"] = "empty"
    scan_time: str = ""
    market_open: bool = False
    data_date: str | None = None
    source: str = "Unusual Whales"
    lookback_days: int = 0
    z_window: int = 63
    basis: Literal["live", "eod"] = "eod"
    signal: GrgSignal = Field(default_factory=GrgSignal)
    assets: GrgAssets | None = None
    gates: list[GrgGate] = Field(default_factory=list)
    history: list[GrgHistoryEntry] = Field(default_factory=list)
    events: GrgEvents = Field(default_factory=GrgEvents)
    top_bottom: GrgTopBottom = Field(default_factory=GrgTopBottom)


EMPTY_GRG_RESPONSE = GrgResponse()


class GexScanResponse(BaseModel):
    """Response body for POST /api/regime/gex/scan.

    The scan runs synchronously and has persisted ``row_id`` when this returns.
    """

    status: Literal["ok"] = "ok"
    scanner: Literal["gex"] = "gex"
    ticker: str
    row_id: int


class GrgScanResponse(BaseModel):
    """Response body for POST /api/regime/grg/scan."""

    status: Literal["ok", "skipped"] = "ok"
    scanner: Literal["grg"] = "grg"
    row_id: int | None = None
    reason: str | None = None
