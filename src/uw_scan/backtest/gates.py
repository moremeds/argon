"""OOS discipline gates — the single home for logic previously duplicated in
reports/skew_markout.py (_rv_walkforward/_rv_survives_window_gate) and
reports/vrp_markout_core.py (walkforward/survives_quarter_gate).

quarter_gate is the standing per-window catastrophic-degradation rule
(feedback_per_regime_catastrophic_gate): an aggregate that hides a sub-window
blowup does not survive.
"""

from __future__ import annotations

from collections import defaultdict

from uw_scan.backtest.splitters import time_ordered_holdout


def quarter_gate(obs: list[dict], overall_mean: float, value_key: str) -> bool:
    """Fail if ANY calendar quarter reverses the aggregate sign with LARGER
    magnitude. Near-zero aggregate auto-fails. obs need 'market_date' + value_key."""
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


def walkforward_gate(
    obs: list[dict],
    *,
    value_key: str,
    min_n: int,
    threshold: float,
    holdout_threshold: float,
    holdout_frac: float = 0.40,
    expected_sign: int | None = None,
) -> dict:
    """Holdout gate on the mean of obs[value_key]. Holdout = latest holdout_frac
    by market_date (time-ordered, no leak). expected_sign=+1/-1: one-sided —
    both means must carry that sign, magnitudes gated on abs. None: two-sided —
    full/holdout signs must agree. Below min_n the means stay descriptive and
    both gates are False. Thresholds are positive floors."""
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
    ordered, holdout = time_ordered_holdout(
        obs, key=lambda o: o["market_date"], frac=holdout_frac
    )
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
    if expected_sign is not None:
        sign_ok = (mean_full * expected_sign > 0) and (
            mean_hold is not None and mean_hold * expected_sign > 0
        )
    else:
        sign_ok = mean_hold is not None and (mean_full * mean_hold > 0)
    mag_ok = abs(mean_full) >= threshold and (
        mean_hold is not None and abs(mean_hold) >= holdout_threshold
    )
    return {
        "mean": mean_full,
        "mean_holdout": mean_hold,
        "n": n,
        "n_holdout": len(holdout),
        "survives_walkforward": bool(sign_ok and mag_ok),
        "survives_window_gate": quarter_gate(ordered, mean_full, value_key),
    }
