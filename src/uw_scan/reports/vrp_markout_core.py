"""Shared VRP markout engine (the measurement floor + reusable OOS hygiene).

All axis runs (harvest, sector, multi-horizon, directional, ΔVRP-reversion)
build observations through these primitives so they sit on ONE corrected
measurement layer: corporate-action-adjusted prices + exact forward realized
vol + the standing walk-forward / per-quarter-gate OOS discipline.

Design: docs/superpowers/plans/2026-06-22-vrp-research-expansion.md
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import date as _date

ANNUALIZATION = math.sqrt(252.0)
HOLDOUT_FRAC = 0.40
MIN_N = 20


def apply_split_adjustment(
    prices: list[tuple[_date, float]],
    actions: list[dict],
    *,
    adjust_dividends: bool = False,
) -> list[tuple[_date, float]]:
    """Back-adjust a raw close series for splits (always) and dividends (opt-in)
    so a corporate-action day is not a spurious log return. Splits: every bar
    STRICTLY BEFORE execution_date is divided by the split ratio. Dividends
    (default OFF — ISSUE-7): scale bars strictly before the ex-date by
    (1 - cash / last_close_before_ex) — the reference is the last cum-dividend
    close, NOT the ex-date close (ISSUE-6). Multiplicative factors compound, so
    multiple actions combine correctly regardless of order."""
    if not prices:
        return []
    ordered = sorted(prices, key=lambda p: p[0])
    factor = [1.0] * len(ordered)
    splits = [a for a in actions if a["event_type"] == "split" and a.get("split_ratio")]
    for a in splits:
        ratio = float(a["split_ratio"])
        if ratio <= 0:
            continue
        for idx, (d, _v) in enumerate(ordered):
            if d < a["event_date"]:
                factor[idx] /= ratio
    if adjust_dividends:
        divs = [
            a for a in actions if a["event_type"] == "dividend" and a.get("cash_amount")
        ]
        for a in divs:
            ex = a["event_date"]
            # reference = last close STRICTLY BEFORE ex (the cum-dividend close)
            ref = None
            for d, v in ordered:
                if d < ex:
                    ref = v
                else:
                    break
            if ref is None or ref <= 0:
                continue
            mult = 1.0 - float(a["cash_amount"]) / ref
            if not (0.0 < mult <= 1.0):
                continue
            for idx, (d, _v) in enumerate(ordered):
                if d < ex:
                    factor[idx] *= mult
    return [(d, v * factor[idx]) for idx, (d, v) in enumerate(ordered)]


def forward_realized_vol(
    prices: list[tuple[_date, float]],
    i: int,
    horizon: int,
    *,
    max_abs_logret: float = 0.5,
) -> float | None:
    """Annualized realized vol over the POSITIONAL window [i, i+horizon] from a
    (already-adjusted) price series — sample stdev (ddof=1) of daily log returns
    × sqrt(252). Matches reports/volatility_series.py::_fill_rv_from_price (pandas
    .rolling().std() is ddof=1) so it is unit-consistent with vrp_daily's IV−RV.
    None if the window runs past the tail or any price is non-positive.

    ADVERSARIAL GUARD (Pass-3): if any single-day |log return| exceeds
    max_abs_logret (default 0.5 ≈ a 65% one-day move), return None — for our
    large-cap/ETF universe that is almost certainly an UNADJUSTED split that
    corporate-actions coverage missed, not a real move; scoring it would inject a
    huge fake RV. Dropping the observation is the safe failure."""
    j = i + horizon
    if i < 0 or j >= len(prices):
        return None
    window = prices[i : j + 1]
    rets: list[float] = []
    for k in range(1, len(window)):
        p0, p1 = window[k - 1][1], window[k][1]
        if p0 <= 0 or p1 <= 0:
            return None
        r = math.log(p1 / p0)
        if abs(r) > max_abs_logret:
            return None  # unadjusted split leaked through → don't trust this window
        rets.append(r)
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var) * ANNUALIZATION


def survives_quarter_gate(obs: list[dict], overall_mean: float, value_key: str) -> bool:
    """Per-calendar-quarter catastrophic-degradation gate (standing rule). Fail if
    ANY quarter reverses the aggregate sign with LARGER magnitude. Near-zero
    aggregate auto-fails. Generalized over value_key so every target reuses it."""
    if abs(overall_mean) < 1e-9:
        return False
    by_q: dict[tuple[int, int], list[float]] = defaultdict(list)
    for o in obs:
        d = o["market_date"]
        by_q[(d.year, (d.month - 1) // 3)].append(o[value_key])
    for vals in by_q.values():
        if not vals:
            continue
        m = sum(vals) / len(vals)
        if m * overall_mean < 0 and abs(m) > abs(overall_mean):
            return False
    return True


def walkforward(
    obs: list[dict],
    *,
    min_n: int = MIN_N,
    threshold: float,
    holdout_threshold: float,
    value_key: str = "value",
    positive_only: bool = True,
) -> dict:
    """Walk-forward holdout on the mean of obs[value_key]. positive_only=True for
    one-sided claims (harvest > 0); False for two-sided (directional tilt, ΔVRP)
    where the magnitude floor applies to |mean| and the sign must agree between
    full and holdout. Holdout = latest HOLDOUT_FRAC of obs by market_date (no
    leak). Means are descriptive for any n>=1; gates require min_n."""
    n = len(obs)
    base = {
        "mean": None,
        "mean_holdout": None,
        "n": 0,
        "n_holdout": 0,
        "survives_walkforward": False,
        "survives_window_gate": False,
    }
    if n == 0:
        return base
    ordered = sorted(obs, key=lambda o: o["market_date"])
    cut = int(round(n * (1.0 - HOLDOUT_FRAC)))
    holdout = ordered[cut:]
    mean_full = sum(o[value_key] for o in ordered) / n
    mean_hold = sum(o[value_key] for o in holdout) / len(holdout) if holdout else None
    if n < min_n:
        return {
            **base,
            "mean": mean_full,
            "mean_holdout": mean_hold,
            "n": n,
            "n_holdout": len(holdout),
        }
    if positive_only:
        sign_ok = mean_full > 0 and mean_hold is not None and mean_hold > 0
        mag_ok = mean_full >= threshold and (
            mean_hold is not None and mean_hold >= holdout_threshold
        )
    else:
        sign_ok = mean_hold is not None and (mean_full * mean_hold > 0)
        mag_ok = abs(mean_full) >= threshold and (
            mean_hold is not None and abs(mean_hold) >= holdout_threshold
        )
    survives_wf = bool(sign_ok and mag_ok)
    survives_window = survives_quarter_gate(ordered, mean_full, value_key)
    return {
        "mean": mean_full,
        "mean_holdout": mean_hold,
        "n": n,
        "n_holdout": len(holdout),
        "survives_walkforward": survives_wf,
        "survives_window_gate": survives_window,
    }
