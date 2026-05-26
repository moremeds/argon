"""Shared primitives for Trade Insights AI Pydantic contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class TradeInsightAiBase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=False)


TradeIntent = Literal["directional_swing", "range_income"]
DirectionalBias = Literal["LONG_DELTA", "SHORT_DELTA", "WAIT"]
EntryState = Literal["ACTIVE", "CONDITIONAL", "NO_ENTRY"]
UnderlyingPath = Literal[
    "bullish_continuation",
    "bearish_rejection",
    "downside_break",
    "pinned_no_directional_entry",
    "data_insufficient",
]
DteBand = Literal["momentum", "standard", "trend"]
LongLegRole = Literal[
    "trigger_level",
    "support_reclaim",
    "atm_delta_anchor",
    "deep_itm_proxy",
    "n/a",
]
ShortLegRole = Literal[
    "target_level",
    "next_call_wall",
    "second_magnet",
    "next_put_wall",
    "next_downside_target",
    "n/a",
]
ThesisArchetype = Literal[
    "resistance_rejection",
    "support_breakdown",
    "breakout_continuation",
    "pin_no_trade",
    "data_insufficient",
]
AntiPinDirection = Literal["upside", "downside", "none"]
ConsensusGrade = Literal["full", "partial", "divergent", "missing"]
OptionType = Literal["call", "put"]
OptionSide = Literal["long", "short"]
TradeInsightAiProvider = Literal["codex", "claude"]
