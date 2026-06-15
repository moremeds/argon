"""Scanner API response models (spec §8)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel

SignalType = Literal[
    "deep_conviction_flow",
    "dark_pool_accumulation",
    "earnings_iv_crush",
    "gex_pinning",
]


class ScannerSignalHit(BaseModel):
    signal_type: SignalType
    tier: Literal[1, 2]
    score: Decimal
    evidence: dict[str, Any]
    freshness: Literal["live", "stale", "unavailable"]


class ScannerContextFlag(BaseModel):
    layer: Literal["pcr_sentiment"]
    label: str
    value: Decimal | None


class ScannerGatesStatus(BaseModel):
    earnings: Literal["pass", "block"]
    liquidity: Literal["pass", "block"]
    regime: Literal["pass", "block"]


class ScannerCandidate(BaseModel):
    ticker: str
    spot: Decimal | None
    is_type_f: bool
    raw_score: Decimal
    confluence_score: Decimal
    final_score: Decimal
    hits: list[ScannerSignalHit]
    context_flags: list[ScannerContextFlag]
    gates: ScannerGatesStatus
    bias: Literal["bullish", "bearish", "neutral", "mixed"]
    bias_strength: Literal["strong", "moderate", "weak"] | None = None
    setup: Literal["ready", "caution", "blocked"]
    setup_reason: str | None = None
    scanned_at: datetime


class ScannerGatedTicker(BaseModel):
    ticker: str
    reason: Literal["regime_block", "stale_scan"]
    blocking_chip: Literal["SUSPENDED", "DEGRADED"] | None = None
    scanned_at: datetime | None


class ScannerResponse(BaseModel):
    scanned_universe_size: int
    candidates_with_hits: int
    candidates: list[ScannerCandidate]
    # Deprecated-empty compatibility field. Legacy clients may still expect
    # the key, but scanner regime no longer hard-gates candidates.
    gated: list[ScannerGatedTicker]
    generated_at: datetime


class DiscoveryCandidate(BaseModel):
    """Non-watchlist ticker scored by the edge-quality model (premium-free).

    Replaces the prior DCF-only shape. Dark-pool direction/strength/sustained +
    options↔DP confluence are surfaced per card. EIC/GEX still need a deep scan
    (promote to the watchlist).
    """

    ticker: str
    bias: Literal["bullish", "bearish", "neutral", "mixed"]
    bias_strength: Literal["strong", "moderate", "weak"] | None = None
    direction: Literal["long", "short"] | None = None
    score: Decimal
    score_model: str
    score_breakdown: dict[str, Any] = {}
    dp_direction: (
        Literal["ACCUMULATION", "DISTRIBUTION", "NEUTRAL", "NO_DATA"] | None
    ) = None
    dp_strength: Decimal | None = None
    dp_sustained_days: int = 0
    confluence: bool = False
    vol_oi: Decimal | None = None
    sweeps: int = 0
    alert_count: int = 0
    spot: Decimal | None = None
    dp_status: str | None = None
    sector: str | None = None
    scored_at: datetime | None = None
    latest_alert_at: datetime | None = None


class DiscoveryResponse(BaseModel):
    candidates: list[DiscoveryCandidate]
    fetched_at: datetime
    scored_at: datetime | None = None
    source: Literal["scanner_candidate_snapshots"] = "scanner_candidate_snapshots"
    alerts_pulled: int
    earnings_unknown_dropped: int = 0
