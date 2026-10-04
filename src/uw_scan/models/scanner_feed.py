"""Scanner API response models (spec §8)."""

from __future__ import annotations

from datetime import date, datetime
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


class ValueCandidate(BaseModel):
    """One name whose price sits at or below its OWN `buy_below` level.

    A membership fact about a single company, not a placement against the other
    rows. `spot_percentile` is a YIELD percentile — high means cheap versus this
    name's own past — and is carried for the reader, never as a sort key.
    """

    ticker: str
    company_type: str
    #: Non-null HERE though the column is nullable (migration 124): every row
    #: reaching this model cleared `buy_below IS NOT NULL`, and a priced row
    #: always has a method. That join is enforced in the schema, not by comment
    #: — `valuation_anchors_methodless_is_refusal` (migration 124) rejects a
    #: methodless row carrying any level, so the shape that would fail response
    #: validation here cannot be written. Widening this to `str | None` would
    #: mean the constraint was dropped; check that before touching it.
    method: str
    spot: Decimal | None
    buy_below: Decimal | None
    observe_mid: Decimal | None
    risk_above: Decimal | None
    spot_percentile: float | None
    history_quarters: int
    confidence: Literal["high", "medium", "low", "none"]
    confidence_reasons: list[str] = []
    # True = out of its zone at the previous as_of and in it now. False = already
    # in. Null = no prior row inside the lookback, so no comparison was possible.
    entered: bool | None = None
    as_of: date


class ValueScanResponse(BaseModel):
    """Every name currently inside its own buy zone.

    Deliberately unranked. Ordering names by cheapness measured INVERTED in this
    universe (`book_to_price` 2q IC -0.0365, t -2.32), so the list is sorted by
    entry event and then alphabetically. `engine_version` is on the response
    because a band is only readable beside the method that produced it.
    """

    candidates: list[ValueCandidate]
    engine_version: str
    # Spot date the bands were computed against, not the date the job ran.
    as_of: date | None
    # Names carrying a band at `as_of`, i.e. the denominator for the list length.
    banded_universe: int
    generated_at: datetime
