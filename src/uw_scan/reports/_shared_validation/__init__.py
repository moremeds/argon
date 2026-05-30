"""Shared validation constants and utilities for trade_insights_ai and trade_blast.

Both lanes share the same vocabulary, leniency coercers, and structural
validators.  Only the constants, normalization helpers, and rule functions
live here — prompt text, analysis_input builders, and lane-specific additions
(e.g. framework coercion) stay in their respective packages.
"""

from __future__ import annotations

from .constants import (
    DIRECTIONAL_BIAS_VALUES,
    DIRECTIONAL_SWING_STRUCTURES,
    DTE_BAND_RANGES,
    DTE_BAND_VALUES,
    ENTRY_STATE_VALUES,
    FINAL_RATING_VALUES,
    PREFERRED_STRATEGY_FAMILY_IDS,
    RANGE_INCOME_STRUCTURES,
    STRATEGY_FAMILY_IDS,
    TRADE_INTENT_VALUES,
    UNDERLYING_PATH_VALUES,
)

__all__ = [
    "DIRECTIONAL_BIAS_VALUES",
    "DIRECTIONAL_SWING_STRUCTURES",
    "DTE_BAND_RANGES",
    "DTE_BAND_VALUES",
    "ENTRY_STATE_VALUES",
    "FINAL_RATING_VALUES",
    "PREFERRED_STRATEGY_FAMILY_IDS",
    "RANGE_INCOME_STRUCTURES",
    "STRATEGY_FAMILY_IDS",
    "TRADE_INTENT_VALUES",
    "UNDERLYING_PATH_VALUES",
]
