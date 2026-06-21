from __future__ import annotations

from datetime import date, timedelta

from uw_scan.reports import vrp_markout as vm


def _obs(values, start=date(2026, 1, 1)):
    """Build obs spaced 1 day apart so the quarter bucketing is well-defined."""
    return [
        {"market_date": start + timedelta(days=i), "realized_vrp": v}
        for i, v in enumerate(values)
    ]


def test_quarter_gate_passes_when_all_quarters_agree():
    obs = _obs([0.05] * 30)
    assert vm._survives_quarter_gate(obs, 0.05) is True


def test_quarter_gate_fails_on_larger_opposite_quarter():
    # Aggregate stays POSITIVE while Q1 reverses sign with LARGER magnitude.
    # (5*-0.10 + 30*0.05)/35 = +0.0286; Q1 mean -0.10 → |Q1| > |overall| → fail.
    q1 = _obs([-0.10] * 5, start=date(2026, 1, 1))  # Q1, mean -0.10
    q2 = _obs([0.05] * 30, start=date(2026, 4, 1))  # Q2, mean +0.05
    obs = q1 + q2
    overall = sum(o["realized_vrp"] for o in obs) / len(obs)
    assert overall > 0  # aggregate positive (the gate must still fail)
    assert vm._survives_quarter_gate(obs, overall) is False


def test_quarter_gate_fails_on_near_zero_aggregate():
    assert vm._survives_quarter_gate(_obs([0.0] * 10), 0.0) is False


def test_walkforward_below_min_n_still_reports_descriptive_mean():
    # AC3 / ISSUE-7: descriptive mean is computed even below min_n (conditioning
    # evidence stays legible); only the verdict gate is False.
    res = vm._walkforward_harvest(_obs([0.05] * 5))
    assert res["n"] == 5
    assert res["mean_realized_vrp"] == 0.05  # NOT None
    assert res["survives_walkforward"] is False  # n < min_n
    assert res["survives_window_gate"] is False


def test_walkforward_passes_positive_stable_harvest():
    res = vm._walkforward_harvest(_obs([0.05] * 40))
    assert res["n"] == 40
    assert res["n_holdout"] == 16  # round(40 * 0.40)
    assert res["mean_realized_vrp"] > 0
    assert res["mean_holdout"] > 0
    assert res["survives_walkforward"] is True
    assert res["survives_window_gate"] is True


def test_walkforward_fails_below_full_threshold():
    # positive but tiny (< 0.02) → full-sample magnitude floor fails
    res = vm._walkforward_harvest(_obs([0.005] * 40))
    assert res["mean_realized_vrp"] == 0.005  # still reported descriptively
    assert res["survives_walkforward"] is False


def test_walkforward_fails_when_holdout_below_floor():
    # ISSUE-3: full mean clears 0.02 but the holdout is positive yet immaterial
    # (< HOLDOUT_THRESHOLD 0.01). Without a holdout floor this would wrongly pass.
    vals = [0.05] * 24 + [0.005] * 16  # full=(1.2+0.08)/40=0.032; holdout=0.005
    res = vm._walkforward_harvest(_obs(vals))
    assert res["mean_realized_vrp"] > 0.02
    assert 0 < res["mean_holdout"] < 0.01
    assert res["survives_walkforward"] is False


def test_walkforward_fails_when_holdout_turns_negative():
    # full mean positive, but the latest 40% is negative → sign disagreement
    vals = [0.10] * 24 + [-0.05] * 16
    res = vm._walkforward_harvest(_obs(vals))
    assert res["mean_realized_vrp"] > 0
    assert res["mean_holdout"] < 0
    assert res["survives_walkforward"] is False


def test_walkforward_min_n_boundary():
    # ISSUE-9: verdict eligibility flips exactly at n == MIN_N (20).
    assert vm._walkforward_harvest(_obs([0.05] * 19))["survives_walkforward"] is False
    assert vm._walkforward_harvest(_obs([0.05] * 20))["survives_walkforward"] is True
