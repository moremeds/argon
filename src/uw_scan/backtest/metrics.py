"""Performance-metric primitives for the backtest harness.

Pure functions over per-period SIMPLE returns (0.01 == +1%). Population std
(ddof=0) everywhere — these reproduce the numbers of the sweep's former
_sharpe_maxdd (now removed; _vrp_macro_param_sweep imports monthly_summary),
whose saved trace (docs/research/vrp/) is the reproduction target. Degenerate
inputs return nan/0.0 rather than raising so sweep summaries stay serializable.
Drawdown is on the ADDITIVE cumulative curve (ROR units), not compounded —
same convention as the legacy sweep.
"""

from __future__ import annotations

from math import sqrt
from statistics import fmean, pstdev
from typing import Mapping, Sequence


def annualized_sharpe(returns: Sequence[float], *, periods_per_year: int) -> float:
    """mean/pstdev * sqrt(periods_per_year). nan for empty or zero-dispersion."""
    if not returns:
        return float("nan")
    sd = pstdev(returns)
    if sd == 0:
        return float("nan")
    return fmean(returns) / sd * sqrt(periods_per_year)


def additive_max_drawdown(returns: Sequence[float]) -> float:
    """Worst peak-to-trough of the additive cumulative curve. <= 0."""
    cum = peak = mdd = 0.0
    for x in returns:
        cum += x
        peak = max(peak, cum)
        mdd = min(mdd, cum - peak)
    return mdd


def hit_rate(returns: Sequence[float]) -> float:
    if not returns:
        return float("nan")
    return sum(1 for r in returns if r > 0) / len(returns)


def zero_filled_monthly(monthly: Mapping[tuple[int, int], float]) -> list[float]:
    """Contiguous (year, month)-keyed span, missing months as 0.0 — exact port
    of the span logic in the former _sharpe_maxdd (a month with no exits is a flat month,
    not a skipped one; skipping would overstate Sharpe)."""
    if not monthly:
        return []
    yms = sorted(monthly)
    (y0, m0), (y1, m1) = yms[0], yms[-1]
    series: list[float] = []
    y, m = y0, m0
    while (y, m) <= (y1, m1):
        series.append(monthly.get((y, m), 0.0))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return series


def monthly_summary(monthly: Mapping[tuple[int, int], float]) -> dict:
    """Drop-in replacement for the sweep's former _sharpe_maxdd (now removed).
    Returns {'sharpe', 'maxdd', 'annror'} over the zero-filled monthly series."""
    series = zero_filled_monthly(monthly)
    if not series:
        return {"sharpe": float("nan"), "maxdd": 0.0, "annror": 0.0}
    return {
        "sharpe": annualized_sharpe(series, periods_per_year=12),
        "maxdd": additive_max_drawdown(series),
        "annror": fmean(series) * 12,
    }
