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
    gated: list[ScannerGatedTicker]
    generated_at: datetime
