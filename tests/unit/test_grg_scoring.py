"""Unit tests for GRG scoring (ported from radon gamma_rotation_gap.py)."""

from __future__ import annotations

import math
from datetime import date, timedelta

from uw_scan.cards import grg_scoring as g


def test_asset_state():
    assert g._asset_state(1.0) == "CUSHION"
    assert g._asset_state(-1.0) == "WHIP"
    assert g._asset_state(0.0) == "NEUTRAL"


def test_pair_state_all_quadrants():
    assert g._pair_state(1.0, -1.0) == "RISK_ON_DIVERGENCE"
    assert g._pair_state(-1.0, 1.0) == "RISK_OFF_DIVERGENCE"
    assert g._pair_state(1.0, 1.0) == "DUAL_CUSHION"
    assert g._pair_state(-1.0, -1.0) == "DUAL_WHIP"
    assert g._pair_state(0.0, 0.0) == "NEUTRAL"


def test_zscore_series_last_point():
    # Constant series then a jump → last z-score is large & positive.
    vals = [1.0] * 30 + [5.0]
    z = g._zscore_series(vals)
    assert z[-1] > 2.0
    # First 9 points lack the 10-obs minimum → NaN.
    assert math.isnan(z[0])


def test_gate_rows_risk_off_polarity_watch():
    # SPY negative, TLT positive (risk-off): polarity gate WATCHes, spy_cushion FAILs.
    rows = g._gate_rows(
        -2.6, spy_gamma=-1.0, tlt_gamma=1.0, spy_slope_3d=0.5, spy_flip_gap_pct=-0.2
    )
    by_id = {r["id"]: r for r in rows}
    assert by_id["polarity"]["status"] == "WATCH"
    assert by_id["spy_cushion"]["status"] == "FAIL"
    assert by_id["duration_whip"]["status"] == "WATCH"  # TLT positive → not whipping
    assert by_id["magnitude"]["status"] == "PASS"  # |z| >= 2
    assert by_id["flip"]["status"] == "WATCH"  # spot below flip


def test_classify_bottom_watch():
    res = g._classify_signal(
        grg_z=-2.7,
        spy_gamma=-1.0,
        tlt_gamma=1.0,
        spy_slope_3d=0.5,
        spy_flip_gap_pct=0.3,
    )
    assert res["state"] == "RISK_OFF_DIVERGENCE"
    assert res["interpretation"] == "BOTTOM_WATCH"
    assert res["bottom_score"] >= 4


def _mk_rows(values: list[float], start: date) -> list[dict]:
    return [
        {"date": start + timedelta(days=i), "net_gex": v} for i, v in enumerate(values)
    ]


def test_run_analysis_payload_shape():
    # 80 aligned sessions: SPY trending negative, TLT trending positive.
    n = 80
    spy = _mk_rows([1000.0 - 30.0 * i for i in range(n)], date(2026, 1, 1))
    tlt = _mk_rows([1000.0 + 40.0 * i for i in range(n)], date(2026, 1, 1))
    payload = g.run_analysis(
        spy,
        tlt,
        spy_spot=740.0,
        spy_flip=735.0,
        tlt_spot=85.0,
        tlt_flip=None,
        scan_time="2026-06-12T19:37:41Z",
        market_open=False,
    )
    assert (
        payload["data_date"] == (date(2026, 1, 1) + timedelta(days=n - 1)).isoformat()
    )
    assert payload["lookback_days"] == n
    assert payload["z_window"] == 63
    assert payload["signal"]["state"] == "RISK_OFF_DIVERGENCE"
    assert payload["assets"]["SPY"]["state"] == "WHIP"
    assert payload["assets"]["TLT"]["state"] == "CUSHION"
    # SPY above its flip → spot_vs_flip positive.
    assert payload["assets"]["SPY"]["spot_vs_flip_pct"] > 0
    assert payload["assets"]["TLT"]["flip"] is None
    assert len(payload["gates"]) == 6
    assert len(payload["history"]) <= g.HISTORY_DAYS
    assert payload["history"][-1]["state"] == "RISK_OFF_DIVERGENCE"
    # data_date / history dates are ISO strings (no date objects in payload).
    assert isinstance(payload["data_date"], str)
    assert isinstance(payload["history"][-1]["date"], str)


def test_run_analysis_insufficient_observations():
    spy = _mk_rows([1.0] * 10, date(2026, 1, 1))
    tlt = _mk_rows([1.0] * 10, date(2026, 1, 1))
    try:
        g.run_analysis(
            spy,
            tlt,
            spy_spot=1.0,
            spy_flip=1.0,
            tlt_spot=1.0,
            tlt_flip=1.0,
            scan_time="t",
            market_open=False,
        )
        assert False, "expected ValueError"
    except ValueError:
        pass
