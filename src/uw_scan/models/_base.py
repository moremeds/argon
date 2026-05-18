"""Shared model base classes and literals."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class _UwBase(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=False)


def _preserve_public_module(*model_types: type[object]) -> None:
    for model_type in model_types:
        model_type.__module__ = "uw_scan.models"
    for model_type in model_types:
        model_rebuild = getattr(model_type, "model_rebuild", None)
        if model_rebuild is not None:
            model_rebuild(force=True)


MatrixDirection = Literal["vol_up", "vol_down", "neutral", "stale"]
MatrixConsistencyTier = Literal[
    "strict", "strong", "weak", "no_trade", "insufficient_data"
]
VannaConditionalReading = Literal[
    "grind_up", "reverse_selloff", "reflexive_sell_pressure", "weak_noise"
]
CharmRegime = Literal["operative_magnet", "broken_magnet", "opex_vortex", "neutral"]
SkewRegime = Literal["smirk", "accelerated", "crash_smile", "neutral"]
FlowFootprintLabel = Literal[
    "directional_whale", "hedge_flow", "dealer_hedge", "gamma_scalper", "unclassified"
]
