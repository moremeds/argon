"""Vocabulary constants shared by both trade_insights_ai and trade_blast.

Extracted from prompt_text.py so validators and leniency coercers can import
without pulling in either lane's prompt module.
"""

from __future__ import annotations

STRATEGY_FAMILY_IDS = frozenset(
    {
        "long_stock",
        "long_call",
        "long_put",
        "call_debit_spread",
        "put_debit_spread",
        "bull_call_spread",
        "bear_put_spread",
        "call_credit_spread",
        "put_credit_spread",
        "risk_reversal",
        "call_diagonal",
        "put_diagonal",
        "iron_condor",
        "iron_butterfly",
        "butterfly",
        "calendar_spread",
        "covered_call",
        "cash_secured_put",
        "short_strangle",
        "no_trade",
    }
)
PREFERRED_STRATEGY_FAMILY_IDS = STRATEGY_FAMILY_IDS - {"short_strangle"}

DIRECTIONAL_SWING_STRUCTURES = frozenset(
    {
        "long_call",
        "long_put",
        "call_debit_spread",
        "put_debit_spread",
        "bull_call_spread",
        "bear_put_spread",
        "call_diagonal",
        "put_diagonal",
        "no_trade",
    }
)
RANGE_INCOME_STRUCTURES = frozenset(
    {
        "iron_condor",
        "iron_butterfly",
        "butterfly",
        "calendar_spread",
        "call_credit_spread",
        "put_credit_spread",
        "no_trade",
    }
)

TRADE_INTENT_VALUES = ("directional_swing", "range_income")
DIRECTIONAL_BIAS_VALUES = ("LONG_DELTA", "SHORT_DELTA", "WAIT")
ENTRY_STATE_VALUES = ("ACTIVE", "CONDITIONAL", "NO_ENTRY")
UNDERLYING_PATH_VALUES = (
    "bullish_continuation",
    "bearish_rejection",
    "downside_break",
    "pinned_no_directional_entry",
    "data_insufficient",
)
DTE_BAND_VALUES = ("momentum", "standard", "trend")
DTE_BAND_RANGES = {
    "momentum": (14, 30),
    "standard": (31, 44),
    "trend": (45, 75),
}

FINAL_RATING_VALUES = ("A", "B", "C", "D", "F")
