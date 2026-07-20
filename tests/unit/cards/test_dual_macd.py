"""Dual MACD deriver + state machine (ports apex momentum/dual_macd.py)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from uw_scan.cards.technicals import dual_macd_series, dual_macd_state


def _ramp_df(n: int = 400, slope: float = 0.5, start: float = 100.0) -> pd.DataFrame:
    close = start + slope * np.arange(n, dtype=float)
    return pd.DataFrame(
        {
            "as_of": pd.date_range("2023-01-02", periods=n, freq="B").date,
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": np.full(n, 1_000.0),
        }
    )


def test_series_has_all_columns_and_is_finite_at_tail():
    out = dual_macd_series(_ramp_df())
    assert list(out.columns) == [
        "fast_macd_hist_atr",
        "slow_macd_hist_atr",
        "fast_macd_line_atr",
        "fast_macd_signal_atr",
        "fast_macd_delta",
        "slow_macd_delta",
        "fast_macd_delta2",
        "fast_macd_norm",
        "slow_macd_norm",
    ]
    assert np.isfinite(out["fast_macd_hist_atr"].iloc[-1])
    assert np.isfinite(out["slow_macd_hist_atr"].iloc[-1])
    # The charted trio must stay self-consistent: the histogram the pane draws
    # is exactly the gap between the two lines drawn over it.
    tail = out.iloc[-1]
    assert tail["fast_macd_hist_atr"] == pytest.approx(
        tail["fast_macd_line_atr"] - tail["fast_macd_signal_atr"]
    )
    # norms are 0..1 percentile ranks
    assert 0.0 <= out["fast_macd_norm"].iloc[-1] <= 1.0


def test_state_steady_uptrend_is_bullish_no_tactical():
    out = dual_macd_series(_ramp_df())
    st = dual_macd_state(out.iloc[-1])
    # A steady (constant-velocity) ramp keeps the slow histogram positive but
    # decaying toward zero, so the faithful apex state machine reads the
    # bullish family as BULLISH or DETERIORATING (both require h_slow > 0).
    # The load-bearing invariant is structural bullishness (h_slow > 0) with
    # no countertrend tactical signal.
    assert st["slow_hist"] > 0
    assert st["trend_state"] in {"BULLISH", "DETERIORATING"}
    assert st["tactical_signal"] == "NONE"
    assert st["confidence"] == 0.0
    assert st["momentum_balance"] in {"FAST_DOMINANT", "SLOW_DOMINANT", "BALANCED"}


def test_state_dip_buy_branch():
    # Directly exercise the state truth table: bullish structure (slow>0),
    # fast dipped negative but decelerating (dh_fast>=0, |dh_fast|>|dh_slow|).
    row = {
        "slow_macd_hist_atr": 0.8,
        "fast_macd_hist_atr": -0.4,
        "slow_macd_delta": 0.01,
        "fast_macd_delta": 0.20,
        "fast_macd_delta2": 0.10,
        "slow_macd_norm": 0.6,
        "fast_macd_norm": 0.5,
    }
    st = dual_macd_state(row)
    assert st["tactical_signal"] == "DIP_BUY"
    assert 0.0 < st["confidence"] <= 1.0


def test_state_rally_sell_branch():
    row = {
        "slow_macd_hist_atr": -0.8,
        "fast_macd_hist_atr": 0.4,
        "slow_macd_delta": -0.01,
        "fast_macd_delta": -0.20,
        "fast_macd_delta2": -0.10,
        "slow_macd_norm": 0.6,
        "fast_macd_norm": 0.5,
    }
    st = dual_macd_state(row)
    assert st["tactical_signal"] == "RALLY_SELL"
    assert 0.0 < st["confidence"] <= 1.0


def test_state_freeze_zone_is_balanced():
    row = {
        "slow_macd_hist_atr": 0.05,
        "fast_macd_hist_atr": 0.02,
        "slow_macd_delta": 0.0,
        "fast_macd_delta": 0.0,
        "fast_macd_delta2": 0.0,
        "slow_macd_norm": 0.10,
        "fast_macd_norm": 0.10,
    }
    assert dual_macd_state(row)["momentum_balance"] == "BALANCED"


def test_state_handles_nan_row_without_raising():
    row = {
        k: float("nan")
        for k in (
            "slow_macd_hist_atr",
            "fast_macd_hist_atr",
            "slow_macd_delta",
            "fast_macd_delta",
            "fast_macd_delta2",
            "slow_macd_norm",
            "fast_macd_norm",
        )
    }
    st = dual_macd_state(row)
    assert st["trend_state"] == "BEARISH"  # all-zero fallthrough
    assert st["tactical_signal"] == "NONE"
