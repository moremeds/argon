"""Claude lenient coercion for the trade_blast lane.

Delegates to the shared trade_insights_ai coercer with the blast lane's
prompt version and framework-block coercer wired in — the only deltas this
lane needs over the base coercion pipeline. The framework{} block itself is
coerced by `leniency.framework`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from uw_scan.reports.trade_blast.leniency.framework import _coerce_framework
from uw_scan.reports.trade_blast.prompt_text import PROMPT_VERSION
from uw_scan.reports.trade_insights_ai.leniency.coerce import (
    _coerce_claude_outcome_dict as _base_coerce_claude_outcome_dict,
)


def _coerce_claude_outcome_dict(
    raw: Any,
    deterministic_payload: dict[str, Any],
    *,
    produced_at: datetime,
    expected_analysis_input_hash: str,
) -> dict[str, Any]:
    """Coerce Claude's free-form JSON into a TradeInsightAiOutcome-shaped dict,
    including the blast lane's additive framework{} block."""
    return _base_coerce_claude_outcome_dict(
        raw,
        deterministic_payload,
        produced_at=produced_at,
        expected_analysis_input_hash=expected_analysis_input_hash,
        prompt_version=PROMPT_VERSION,
        framework_coercer=_coerce_framework,
    )
