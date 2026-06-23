"""Iteration-4 robustness studies on the macro short-vol WINNER.

Pure orchestration over the validated ledger (reports/vrp_capital_account.simulate_account)
and pricing (reports/vrp_structure.build_bull_put_spread). Adds the analysis the ledger
deliberately omits: smallest viable starting capital, the SPY buy-and-hold benchmark, a
geometric compounding-metric path, and the weekday / bear-start / Monte-Carlo experiments.
No new deps — stdlib statistics + random only. Every result returns a dict the runner
(scripts/research/vrp_robustness_run.py) persists to a CSV. Reproduce: see that runner.
"""

from __future__ import annotations

import math
from datetime import date as _date
from statistics import fmean, pstdev
from typing import Any

from uw_scan.reports.vrp_structure import build_bull_put_spread

# NOTE: Tasks 5 and 6 EXTEND this import block (via Edit, never inline) to add
# `dataclasses`, the vrp_capital_account symbols, `random`, and MacroSignalConfig.
CONTRACT_MULTIPLIER = 100


def _pct(values: list[float], q: float) -> float:
    """Linear-interpolated percentile (q in [0,1]); empty → nan, single → that value."""
    xs = sorted(v for v in values if v is not None and not math.isnan(v))
    if not xs:
        return float("nan")
    if len(xs) == 1:
        return xs[0]
    pos = q * (len(xs) - 1)
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return xs[lo]
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def min_viable_capital(
    loaded,
    settings,
    *,
    short_delta: float = 0.25,
    wing_frac: float = 0.5,
    hold: int = 30,
    min_date: _date | None = None,
    base_risk_pcts: tuple[float, ...] = (0.10, 0.20, 0.50, 1.0),
) -> dict[str, Any]:
    """Smallest C0 that affords >=1 bull-put spread. Returns the first tradeable entry's
    max-loss/contract, the max over the post-start period (what's needed to never skip as
    spot rises), and the floor C0 per risk-%: ceil(mlpc / brp) to $1k."""
    r = settings.vrp_risk_free_rate
    iv_map = {row["market_date"]: row["iv"] for row in loaded.rows}
    first_mlpc: float | None = None
    first_date: _date | None = None
    max_mlpc = 0.0
    for pi in range(0, max(0, len(loaded.adj) - hold)):
        d, s0 = loaded.adj[pi]
        if min_date and d < min_date:
            continue
        iv = iv_map.get(d)
        if iv is None or iv <= 0 or s0 <= 0:
            continue
        try:
            st = build_bull_put_spread(
                s0,
                float(iv),
                hold / 252.0,
                r,
                short_delta=short_delta,
                wing_delta=short_delta * wing_frac,
            )
        except ValueError:
            continue
        mlpc = st.max_loss * CONTRACT_MULTIPLIER
        if first_mlpc is None:
            first_mlpc, first_date = mlpc, d
        max_mlpc = max(max_mlpc, mlpc)
    if first_mlpc is None:
        return {
            "first_entry_date": None,
            "first_mlpc": 0.0,
            "max_mlpc": 0.0,
            "c0_floor": {},
        }

    def _ceil1k(x: float) -> float:
        return math.ceil(x / 1000.0) * 1000.0

    return {
        "first_entry_date": first_date,
        "first_mlpc": first_mlpc,
        "max_mlpc": max_mlpc,
        "c0_floor": {brp: _ceil1k(first_mlpc / brp) for brp in base_risk_pcts},
    }


def buy_and_hold(
    adj, capital: float, rf: float, *, min_date: _date | None = None
) -> dict:
    """SPY buy-and-hold benchmark: invest `capital` at the first spot on/after min_date,
    mark to each close. Sharpe on monthly equity-relative returns (annualised)."""
    pts = [
        (d, s) for d, s in adj if s and s > 0 and (min_date is None or d >= min_date)
    ]
    if len(pts) < 2:
        return {
            "ann_return": float("nan"),
            "cagr": float("nan"),
            "sharpe": float("nan"),
            "maxdd_dollars": 0.0,
            "maxdd_pct": 0.0,
            "years": 0.0,
            "start": None,
            "end": None,
        }
    s0 = pts[0][1]
    equity = [(d, capital * s / s0) for d, s in pts]
    by_month: dict[tuple[int, int], float] = {}
    for d, e in equity:
        by_month[(d.year, d.month)] = e  # last write per month wins (month-end)
    months = [by_month[k] for k in sorted(by_month)]
    rets = [months[i] / months[i - 1] - 1.0 for i in range(1, len(months))]
    sd = pstdev(rets) if len(rets) > 1 else 0.0
    sharpe = (fmean(rets) / sd * math.sqrt(12)) if sd > 0 else float("nan")
    peak = mdd = 0.0
    for _d, e in equity:
        peak = max(peak, e)
        mdd = min(mdd, e - peak)
    years = (pts[-1][0] - pts[0][0]).days / 365.25
    cagr = (
        (equity[-1][1] / capital) ** (1.0 / years) - 1.0 if years > 0 else float("nan")
    )
    return {
        "ann_return": fmean(rets) * 12 if rets else float("nan"),
        "cagr": cagr,
        "sharpe": sharpe,
        "maxdd_dollars": mdd,
        "maxdd_pct": mdd / capital if capital else 0.0,
        "years": years,
        "start": pts[0][0],
        "end": pts[-1][0],
    }


def _contiguous_months(
    monthly: dict[tuple[int, int], float],
) -> list[tuple[tuple[int, int], float]]:
    if not monthly:
        return []
    yms = sorted(monthly)
    (y0, m0), (y1, m1) = yms[0], yms[-1]
    out: list[tuple[tuple[int, int], float]] = []
    y, m = y0, m0
    while (y, m) <= (y1, m1):
        out.append(((y, m), monthly.get((y, m), 0.0)))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def monthly_equity(res, capital: float) -> list[tuple[tuple[int, int], float]]:
    """Month-end $ equity path = capital + running sum of monthly $P&L
    (monthly_excess is net ÷ initial capital, so $P&L_month = excess × capital)."""
    eq = capital
    out: list[tuple[tuple[int, int], float]] = []
    for ym, exc in _contiguous_months(res.monthly_excess):
        eq += exc * capital
        out.append((ym, eq))
    return out


def equity_curve_metrics(equity_points, capital: float, rf: float) -> dict:
    """Geometric metrics for the compounding read: simple monthly returns
    r_t = E_t / E_{t-1} - 1 with E_0 = capital. Sharpe/CAGR/maxDD on that path."""
    if not equity_points:
        return {
            "ann_return": float("nan"),
            "cagr": float("nan"),
            "sharpe": float("nan"),
            "maxdd_dollars": 0.0,
            "maxdd_pct": 0.0,
            "years": 0.0,
        }
    levels = [capital] + [e for _ym, e in equity_points]
    rets = [
        levels[i] / levels[i - 1] - 1.0
        for i in range(1, len(levels))
        if levels[i - 1] > 0
    ]
    sd = pstdev(rets) if len(rets) > 1 else 0.0
    sharpe = (fmean(rets) / sd * math.sqrt(12)) if sd > 0 else float("nan")
    peak = capital
    mdd = 0.0
    for e in levels:
        peak = max(peak, e)
        mdd = min(mdd, e - peak)
    years = len(equity_points) / 12.0
    cagr = (
        (levels[-1] / capital) ** (1.0 / years) - 1.0
        if (years > 0 and levels[-1] > 0)
        else float("nan")
    )
    return {
        "ann_return": fmean(rets) * 12 if rets else float("nan"),
        "cagr": cagr,
        "sharpe": sharpe,
        "maxdd_dollars": mdd,
        "maxdd_pct": mdd / capital if capital else 0.0,
        "years": years,
    }
