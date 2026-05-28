from __future__ import annotations

import numpy as np

from scripts.backtest_vcg import _composite_daily_rows, _single_proxy_daily_rows
from uw_scan.cards import vcg_scoring


def _prices(n: int, base: float, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return base * np.exp(np.cumsum(rng.normal(0.0, 0.005, size=n)))


def test_single_proxy_daily_payload_exposes_gate_fields() -> None:
    n = 360
    dates = [
        np.datetime_as_string(d, unit="D")
        for d in np.busday_offset("2020-01-01", range(n))
    ]
    model = vcg_scoring.compute_vcg(
        _prices(n, 18.0, seed=1),
        _prices(n, 90.0, seed=2),
        _prices(n, 80.0, seed=3),
    )

    rows, *_ = _single_proxy_daily_rows(model, dates)

    assert rows
    for row in rows:
        assert row["payload"]["interpretation"] == row["level"]
        assert "vix_percentile_rank" in row["payload"]
        assert "vvix_percentile_rank" in row["payload"]


def test_composite_daily_payload_exposes_gate_fields_at_top_level() -> None:
    n = 360
    dates = [
        np.datetime_as_string(d, unit="D")
        for d in np.busday_offset("2020-01-01", range(n))
    ]
    aligned = {
        "VIX": _prices(n, 18.0, seed=10),
        "VVIX": _prices(n, 90.0, seed=11),
        "HYG": _prices(n, 80.0, seed=12),
        "JNK": _prices(n, 100.0, seed=13),
        "LQD": _prices(n, 110.0, seed=14),
    }

    rows, *_ = _composite_daily_rows(
        "risk_parity_3", aligned, dates, vol_window=63, weight_lag=1
    )

    assert rows
    for row in rows:
        assert row["payload"]["interpretation"] == row["level"]
        assert "vix_percentile_rank" in row["payload"]
        assert "vvix_percentile_rank" in row["payload"]
        assert "signal" in row["payload"]
