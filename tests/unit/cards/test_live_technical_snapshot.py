from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from uw_scan.cards.technicals import bars_frame, live_technical_snapshot


def _df(
    n: int = 400,
) -> pd.DataFrame:  # z_vs_200dma needs ~325 rows (SMA200 + 126 std min)
    close = 100.0 + np.cumsum(np.random.default_rng(3).normal(0.05, 1.0, n))
    idx = pd.date_range("2023-01-02", periods=n, freq="B", tz="UTC")
    bars = [
        {
            "time": t.isoformat(),
            "open": float(c),
            "high": float(c) + 1,
            "low": float(c) - 1,
            "close": float(c),
            "volume": 1_000.0,
        }
        for t, c in zip(idx, close)
    ]
    return bars_frame(bars)


def test_live_snapshot_keys_and_splice():
    df = _df()
    prev_close = float(df["close"].iloc[-1])
    snap = live_technical_snapshot(df, prev_close + 5.0, as_of=dt.date(2026, 7, 9))
    assert set(snap) == {
        "z",
        "z_band",
        "rsi14",
        "rsi_z",
        "dual_macd",
        "rv20",
        "kinematics",
        "composite",
    }
    assert snap["dual_macd"]["tactical_signal"] in {"DIP_BUY", "RALLY_SELL", "NONE"}
    # sigmoid / forward_returns are intentionally NOT recomputed live
    assert "sigmoid" not in snap and "forward_returns" not in snap


def test_live_snapshot_moves_with_spot():
    df = _df()
    base = float(df["close"].iloc[-1])
    up = live_technical_snapshot(df, base + 20.0, as_of=dt.date(2026, 7, 9))["z"]
    dn = live_technical_snapshot(df, base - 20.0, as_of=dt.date(2026, 7, 9))["z"]
    assert up > dn  # higher provisional close => higher z vs 200DMA
