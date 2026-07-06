import numpy as np
import pytest

from scripts.research.leap_vega_alpha import (
    atm_iv,
    cross_sectional_ic,
    entry_gap,
    realized_vol,
    stage1_metrics,
)


def test_realized_vol_known_series():
    # 4 closes -> 3 alternating log returns; hand-computed HV.
    # rets = [ln1.02, -ln1.02, ln1.02]; sample-std * sqrt(252) = 0.363.
    hv = realized_vol([100.0, 102.0, 100.0, 102.0], window=3)
    assert hv == pytest.approx(0.363, abs=1e-3)


def test_realized_vol_flat_series_is_zero():
    assert realized_vol([50.0, 50.0, 50.0, 50.0], window=3) == pytest.approx(
        0.0, abs=1e-12
    )


def test_realized_vol_insufficient_data_returns_none():
    assert realized_vol([100.0, 101.0], window=20) is None


def test_atm_iv_interpolates_at_half_delta():
    rows = [
        {"strike": 95.0, "call_iv": 0.32, "call_delta": 0.55},
        {"strike": 105.0, "call_iv": 0.30, "call_delta": 0.45},
        {"strike": 130.0, "call_iv": 0.50, "call_delta": 0.10},
    ]
    # linear interp between (δ0.45, iv0.30) and (δ0.55, iv0.32) at δ=0.5 -> 0.31
    assert atm_iv(rows) == pytest.approx(0.31, abs=1e-6)


def test_atm_iv_rejects_far_from_half_delta():
    # no strike brackets 0.5 and the nearest (δ0.30) is >0.10 away -> None
    rows = [
        {"strike": 120.0, "call_iv": 0.40, "call_delta": 0.30},
        {"strike": 140.0, "call_iv": 0.50, "call_delta": 0.15},
    ]
    assert atm_iv(rows) is None


def test_atm_iv_none_when_no_delta():
    assert atm_iv([{"strike": 100.0, "call_iv": 0.3, "call_delta": None}]) is None


def test_entry_gap_uses_max_hv():
    # max(0.28, 0.35) - 0.20 = 0.15
    assert entry_gap(0.28, 0.35, 0.20) == pytest.approx(0.15)
    assert entry_gap(None, 0.35, 0.20) == pytest.approx(0.15)
    assert entry_gap(0.28, 0.35, None) is None
    assert entry_gap(None, None, 0.20) is None


def test_stage1_metrics_positive_relationship():
    # ΔIV increases monotonically with gap -> rank_ic == 1.0
    gaps = [0.05, 0.10, 0.20, 0.30]
    d_ivs = [-0.01, 0.00, 0.02, 0.05]
    m = stage1_metrics(gaps, d_ivs, threshold=0.15)
    assert m["n"] == 4
    assert m["rank_ic"] == pytest.approx(1.0)
    assert m["flagged_n"] == 2  # gaps 0.20, 0.30
    assert m["hit_rate"] == pytest.approx(1.0)  # both ΔIV > 0
    assert m["flagged_mean_div"] == pytest.approx(0.035)


def test_stage1_metrics_no_flagged():
    m = stage1_metrics([0.01, 0.02], [0.0, 0.0], threshold=0.15)
    assert m["flagged_n"] == 0
    assert np.isnan(m["hit_rate"])


def test_cross_sectional_ic_within_date():
    # Two dates; within EACH date gap-rank matches ΔIV-rank -> per-date IC=1.
    # A whole-sample positive drift would NOT change this (that's the point).
    recs = [
        {"market_date": "2026-01-05", "gap": 0.05, "d_iv": 0.00},
        {"market_date": "2026-01-05", "gap": 0.20, "d_iv": 0.03},
        {"market_date": "2026-01-05", "gap": 0.30, "d_iv": 0.05},
        {"market_date": "2026-01-06", "gap": 0.02, "d_iv": -0.01},
        {"market_date": "2026-01-06", "gap": 0.18, "d_iv": 0.02},
        {"market_date": "2026-01-06", "gap": 0.25, "d_iv": 0.04},
    ]
    m = cross_sectional_ic(recs, threshold=0.15)
    assert m["n_dates"] == 2
    assert m["mean_ic"] == pytest.approx(1.0)
    assert m["mean_diff_harvest"] > 0  # flagged names beat their same-date peers
