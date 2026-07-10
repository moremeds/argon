from __future__ import annotations

import numpy as np
import pandas as pd

from uw_scan.cards.technicals import build_technical_series, build_technical_snapshot


def _bars(n: int = 320) -> list[dict]:
    close = 100.0 + np.cumsum(np.random.default_rng(7).normal(0.05, 1.0, n))
    idx = pd.date_range("2023-01-02", periods=n, freq="B", tz="UTC")
    return [
        {
            "time": t.isoformat(),
            "open": float(c),
            "high": float(c) + 1.0,
            "low": float(c) - 1.0,
            "close": float(c),
            "volume": 1_000.0,
        }
        for t, c in zip(idx, close)
    ]


def test_series_carries_dual_macd_columns():
    out = build_technical_series(_bars())
    for col in (
        "fast_macd_hist_atr",
        "slow_macd_hist_atr",
        "fast_macd_delta",
        "slow_macd_delta",
        "fast_macd_delta2",
        "fast_macd_norm",
        "slow_macd_norm",
    ):
        assert col in out.columns


def test_snapshot_exposes_dual_macd_state():
    snap = build_technical_snapshot(_bars())
    assert snap is not None
    dm = snap["dual_macd"]
    assert set(dm) >= {
        "trend_state",
        "tactical_signal",
        "momentum_balance",
        "confidence",
    }
    assert dm["tactical_signal"] in {"DIP_BUY", "RALLY_SELL", "NONE"}
