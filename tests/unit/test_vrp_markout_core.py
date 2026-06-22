from __future__ import annotations

import math
from datetime import date, timedelta
from decimal import Decimal

from uw_scan.reports.vrp_markout_core import (
    apply_split_adjustment,
    forward_realized_vol,
    survives_quarter_gate,
    walkforward,
)


def _series(vals):
    d0 = date(2024, 1, 1)
    return [(d0 + timedelta(days=i), v) for i, v in enumerate(vals)]


def test_split_adjustment_removes_fake_gap():
    # 100,101,102 then a 10:1 split → raw 10.3,10.4. Back-adjust scales pre-split.
    prices = _series([100.0, 101.0, 102.0, 10.3, 10.4])
    actions = [
        {
            "event_type": "split",
            "event_date": date(2024, 1, 4),
            "split_ratio": Decimal("10"),
            "cash_amount": None,
        }
    ]
    adj = apply_split_adjustment(prices, actions)
    vals = [round(v, 4) for _, v in adj]
    assert vals == [10.0, 10.1, 10.2, 10.3, 10.4]


def test_split_adjustment_empty_is_empty():
    assert apply_split_adjustment([], []) == []


def test_dividend_adjustment_off_by_default():
    prices = _series([100.0, 100.0, 100.0])
    actions = [
        {
            "event_type": "dividend",
            "event_date": date(2024, 1, 3),
            "split_ratio": None,
            "cash_amount": Decimal("1.0"),
        }
    ]
    # default adjust_dividends=False → prices untouched
    assert apply_split_adjustment(prices, actions) == prices
    # opt-in uses last pre-ex close (100) as reference → factor 0.99 on bars before ex
    adj = apply_split_adjustment(prices, actions, adjust_dividends=True)
    assert round(adj[0][1], 4) == 99.0 and round(adj[1][1], 4) == 99.0
    assert adj[2][1] == 100.0  # the ex-date bar itself is not scaled


def test_forward_realized_vol_finite_on_clean_window():
    prices = _series([100, 101, 100, 102, 101, 103, 102, 104])
    rv = forward_realized_vol(prices, 0, 5)
    assert rv is not None and rv > 0 and math.isfinite(rv)


def test_forward_realized_vol_none_on_short_tail():
    prices = _series([100, 101, 102])
    assert forward_realized_vol(prices, 1, 5) is None


def test_forward_realized_vol_guards_unadjusted_split():
    # a 10:1 split that slipped past corp-action coverage → -90% log return
    prices = _series([100, 101, 102, 10.3, 10.4, 10.5])
    assert forward_realized_vol(prices, 0, 5) is None


def test_walkforward_positive_harvest_passes_gates():
    obs = [{"market_date": date(2025, 1, 1), "value": 0.05} for _ in range(30)]
    res = walkforward(obs, min_n=20, threshold=0.02, holdout_threshold=0.01)
    assert res["survives_walkforward"] is True
    assert survives_quarter_gate(obs, res["mean"], "value") is True


def test_walkforward_below_min_n_no_gate_but_descriptive_mean():
    obs = [{"market_date": date(2025, 1, 1), "value": 0.05} for _ in range(5)]
    res = walkforward(obs, min_n=20, threshold=0.02, holdout_threshold=0.01)
    assert res["survives_walkforward"] is False
    assert res["mean"] == 0.05  # descriptive mean still computed


def test_walkforward_two_sided_negative_passes():
    # positive_only=False: a consistently NEGATIVE mean clears the |.| floor.
    obs = [{"market_date": date(2025, 1, 1), "value": -0.04} for _ in range(30)]
    res = walkforward(
        obs,
        min_n=20,
        threshold=0.02,
        holdout_threshold=0.01,
        positive_only=False,
    )
    assert res["survives_walkforward"] is True
    assert res["mean"] < 0


def test_quarter_gate_fails_on_sign_reversal():
    # Q1 strongly negative, Q2 strongly positive → aggregate positive but Q1
    # reverses with larger magnitude → gate fails.
    obs = [{"market_date": date(2025, 1, 10), "value": -0.20} for _ in range(5)]
    obs += [{"market_date": date(2025, 4, 10), "value": 0.10} for _ in range(20)]
    overall = sum(o["value"] for o in obs) / len(obs)
    assert overall > 0
    assert survives_quarter_gate(obs, overall, "value") is False
