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
