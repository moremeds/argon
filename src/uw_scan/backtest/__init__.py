"""Unified backtest harness: engine, splitters, gates, metrics, sweep runner.

Design: docs/superpowers/plans/2026-07-03-backtest-walkforward-harness.md
"""

from uw_scan.backtest.metrics import (
    additive_max_drawdown,
    annualized_sharpe,
    hit_rate,
    monthly_summary,
    zero_filled_monthly,
)
from uw_scan.backtest.splitters import time_ordered_holdout

__all__ = [
    "additive_max_drawdown",
    "annualized_sharpe",
    "hit_rate",
    "monthly_summary",
    "zero_filled_monthly",
    "time_ordered_holdout",
]
