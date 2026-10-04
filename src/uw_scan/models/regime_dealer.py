"""Dealer-regime (per-ticker) response models — over-the-wire regime contract.

Keep stable; update `openapi-typescript` regen when fields change.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# ----------------------------------------------------------------------
# Dealer-regime (per-ticker) — feeds Magnet/Gamma bar + Volatility regime
# panel. See docs/superpowers/archive/plans/2026-05-21-gex-volatility-enrichment.md
# ----------------------------------------------------------------------


class DealerRegimeSignal(BaseModel):
    """Per-ticker dealer regime classification (Γ-driven, with V/C support)."""

    label: Literal["amplifying", "dampening", "neutral"] = "neutral"
    score: float = 0.0
    gamma_score: float = 0.0
    vanna_score: float = 0.0
    charm_score: float = 0.0
    headline: str = ""
    subtitle: str = ""


class GammaDecayBucket(BaseModel):
    dte: int
    expiry: str
    net_gex: float | None = None
    share_pct: float | None = None
    gross_abs_gex: float | None = None
    gross_share_pct: float | None = None


class ClosestLevel(BaseModel):
    label: str
    direction: Literal["up", "down", "flip"] | None = None
    role: Literal["support", "resistance", "accelerator", "flip"] | None = None
    strike: float
    distance_pct: float
    gamma: float | None = None
    rank_kind: Literal["nearest", "dominant"] = "nearest"


class DealerRegimeResponse(BaseModel):
    status: Literal["ok", "empty"] = "empty"
    ticker: str = ""
    scan_time: str = ""
    spot: float | None = None
    net_gex: float | None = None
    prev_close_net_gex: float | None = None
    signal: DealerRegimeSignal = Field(default_factory=DealerRegimeSignal)
    closest_levels: list[ClosestLevel] = Field(default_factory=list)
    odte_gex: float | None = None
    odte_share_pct: float | None = None
    gamma_decay: list[GammaDecayBucket] = Field(default_factory=list)


EMPTY_DEALER_REGIME_RESPONSE = DealerRegimeResponse()
