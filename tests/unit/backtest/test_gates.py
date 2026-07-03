from __future__ import annotations

from datetime import date, timedelta

from uw_scan.backtest.gates import quarter_gate, walkforward_gate

# --- verbatim legacy replica (vrp_markout_core.walkforward before migration) ---
HOLDOUT_FRAC = 0.40


def _legacy_vrp_walkforward(
    obs, *, min_n, threshold, holdout_threshold, value_key="value", positive_only=True
):
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
    survives_window = _legacy_quarter(ordered, mean_full, value_key)
    return {
        "mean": mean_full,
        "mean_holdout": mean_hold,
        "n": n,
        "n_holdout": len(holdout),
        "survives_walkforward": survives_wf,
        "survives_window_gate": survives_window,
    }


def _legacy_quarter(obs, overall_mean, value_key):
    if abs(overall_mean) < 1e-9:
        return False
    by_q: dict = {}
    for o in obs:
        d = o["market_date"]
        by_q.setdefault((d.year, (d.month - 1) // 3), []).append(o[value_key])
    for vals in by_q.values():
        m = sum(vals) / len(vals)
        if m * overall_mean < 0 and abs(m) > abs(overall_mean):
            return False
    return True


def _obs(values, start=date(2025, 1, 6), step_days=7):
    return [
        {"market_date": start + timedelta(days=i * step_days), "value": v}
        for i, v in enumerate(values)
    ]


CASES = [
    _obs([0.02] * 30),  # clean one-sided pass
    _obs([0.02] * 18 + [-0.02] * 12),  # holdout flips sign
    _obs([0.02] * 18 + [0.004] * 12),  # holdout mean 0.004 < 0.005 floor
    _obs([-0.02] * 30),  # wrong sign for positive_only
    _obs([0.02] * 5),  # sub-min_n, descriptive only
    _obs([]),  # empty
    _obs([0.05] * 10 + [-0.30] * 3 + [0.05] * 17),  # Q1 blowup (see direct test)
]


def test_walkforward_gate_matches_legacy_positive_only():
    for obs in CASES:
        old = _legacy_vrp_walkforward(
            obs, min_n=20, threshold=0.01, holdout_threshold=0.005, positive_only=True
        )
        new = walkforward_gate(
            obs,
            value_key="value",
            min_n=20,
            threshold=0.01,
            holdout_threshold=0.005,
            expected_sign=1,
        )
        assert new == old, obs[:2]


def test_walkforward_gate_matches_legacy_two_sided():
    for obs in CASES + [_obs([-0.02] * 30)]:
        old = _legacy_vrp_walkforward(
            obs, min_n=20, threshold=0.01, holdout_threshold=0.005, positive_only=False
        )
        new = walkforward_gate(
            obs,
            value_key="value",
            min_n=20,
            threshold=0.01,
            holdout_threshold=0.005,
            expected_sign=None,
        )
        assert new == old


def test_negative_expected_sign_passes_on_negative_means():
    obs = _obs([-0.02] * 30)
    out = walkforward_gate(
        obs,
        value_key="value",
        min_n=20,
        threshold=0.01,
        holdout_threshold=0.005,
        expected_sign=-1,
    )
    assert out["survives_walkforward"] is True


def test_quarter_gate_direct():
    # weekly dates from 2025-01-06: i=0..12 land in Q1. Q1 mean = (10*.05 - 3*.30)/13
    # ≈ -0.031 — reverses the aggregate (+0.015) with larger magnitude -> gate fails.
    obs = _obs([0.05] * 10 + [-0.30] * 3 + [0.05] * 17)
    mean = sum(o["value"] for o in obs) / len(obs)
    assert abs(mean - 0.015) < 1e-12
    assert quarter_gate(obs, mean, "value") is False
    clean = _obs([0.02] * 30)
    assert quarter_gate(clean, 0.02, "value") is True
    assert quarter_gate(clean, 0.0, "value") is False  # near-zero aggregate auto-fails
