"""Scanner domain models - Decimal-based dataclasses.

Mirrors xenon/scanners/uw/models.py shape but uses Decimal for monetary
and scoring fields per project convention. ScanCandidate carries gates
so the API can surface advisory pass/block on the candidate tile
(spec §8 ScannerGatesStatus).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal


@dataclass(frozen=True)
class SignalHit:
    ticker: str
    signal_type: str
    tier: Literal[1, 2]
    score: Decimal
    evidence: dict[str, Any]
    freshness: Literal["live", "stale", "unavailable"] = "live"


@dataclass(frozen=True)
class ContextFlag:
    ticker: str
    layer: str
    label: str
    value: Decimal | None


@dataclass(frozen=True)
class ScanCandidate:
    ticker: str
    hits: list[SignalHit]
    context_flags: list[ContextFlag]
    raw_score: Decimal
    confluence_score: Decimal
    final_score: Decimal
    is_type_f: bool
    gates: dict[str, str] = field(default_factory=dict)
    bias: Literal["bullish", "bearish", "neutral", "mixed"] = "neutral"
    bias_strength: Literal["strong", "moderate", "weak"] | None = None
    setup: Literal["ready", "caution", "blocked"] = "ready"
    setup_reason: str | None = None


@dataclass(frozen=True)
class DiscoveryCandidate:
    """Non-watchlist ticker surfaced by the market-wide flow-alerts feed.

    Carries only the DCF hit — Dark Pool, EIC, GEX need per-ticker context
    (history, IV rank, GEX curve) we don't have without a deep scan.
    """

    ticker: str
    hit: SignalHit
    bias: Literal["bullish", "bearish", "neutral", "mixed"]
    bias_strength: Literal["strong", "moderate", "weak"] | None
    alert_count: int
    sector: str | None
    latest_alert_at: Any
