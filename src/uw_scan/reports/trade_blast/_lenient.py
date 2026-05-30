"""Compatibility wrapper for Claude Trade Insights AI leniency.

The implementation lives under :mod:`uw_scan.reports.trade_blast.leniency`.
This module preserves historical private imports used by validators and tests.
"""

from __future__ import annotations

from uw_scan.reports.trade_blast.leniency import (
    _coerce_claude_outcome_dict,
    _coerce_option_legs,
)

__all__ = ["_coerce_claude_outcome_dict", "_coerce_option_legs"]
