"""Trade Insights AI package.

Public surface preserved from the pre-split single-module form:
`from uw_scan.reports.trade_insights_ai import X` keeps working for every X
that the lenient coercer, worker job, router, and tests historically used.
"""
from __future__ import annotations

# Constants + prompt text
from .prompt_text import (
    DIRECTIONAL_BIAS_VALUES,
    DIRECTIONAL_SWING_STRUCTURES,
    DTE_BAND_RANGES,
    DTE_BAND_VALUES,
    ENTRY_STATE_VALUES,
    FINAL_RATING_VALUES,
    MARKET_INTELLIGENCE_PROMPT,
    PREFERRED_STRATEGY_FAMILY_IDS,
    PROMPT_VERSION,
    RANGE_INCOME_STRUCTURES,
    STRATEGY_FAMILY_IDS,
    TRADE_INTENT_VALUES,
    UNDERLYING_PATH_VALUES,
)
# Build pipeline + JSON Schema generator
from .analysis_input import (
    _iso_z,
    _to_decimal,
    build_trade_insights_ai_analysis_input,
    build_trade_insights_ai_prompt,
    build_trade_insights_ai_prompt_payload,
    hash_trade_insights_ai_analysis_input,
    trade_insights_ai_output_schema,
)
# Deterministic validators
from .validators import validate_trade_insights_ai_outcome
# Markdown audit rendering
from .markdown import render_trade_insights_ai_markdown
# Cross-module re-export (lenient module owns this; tests historically import
# it via the trade_insights_ai namespace, so we keep the path stable).
# Placed last so our own module is fully constructed before the lenient module
# touches us back during its top-level imports.
from uw_scan.reports.trade_insights_ai_lenient import (  # noqa: E402
    _coerce_claude_outcome_dict,
)

__all__ = [
    "DIRECTIONAL_BIAS_VALUES",
    "DIRECTIONAL_SWING_STRUCTURES",
    "DTE_BAND_RANGES",
    "DTE_BAND_VALUES",
    "ENTRY_STATE_VALUES",
    "FINAL_RATING_VALUES",
    "MARKET_INTELLIGENCE_PROMPT",
    "PREFERRED_STRATEGY_FAMILY_IDS",
    "PROMPT_VERSION",
    "RANGE_INCOME_STRUCTURES",
    "STRATEGY_FAMILY_IDS",
    "TRADE_INTENT_VALUES",
    "UNDERLYING_PATH_VALUES",
    "build_trade_insights_ai_analysis_input",
    "build_trade_insights_ai_prompt",
    "build_trade_insights_ai_prompt_payload",
    "hash_trade_insights_ai_analysis_input",
    "trade_insights_ai_output_schema",
    "validate_trade_insights_ai_outcome",
    "render_trade_insights_ai_markdown",
]
