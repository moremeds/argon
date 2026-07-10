"""Unit tests for uw_scan.cards.technicals — pure math, synthetic labeled series."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest
from uw_scan.cards.technicals import (
    Z_BANDS,
    bars_frame,
    build_technical_series,
    build_technical_snapshot,
    composite_score,
    fit_sigmoid,
    forward_return_table,
    last_pivot_index,
    ma_kinematics,
    relative_strength,
    rsi14,
    slope_regime,
    sma200_slope_ann,
    z_band_label,
    z_vs_200dma,
)


def _bar(day: int, close: float, spread: float = 1.0) -> dict:
    # Synthetic labeled bar in the verified apex shape (ISO time string).
    d = pd.Timestamp("2020-01-01", tz="UTC") + pd.Timedelta(days=day)
    return {
        "time": d.isoformat(),
        "open": close,
        "high": close + spread,
        "low": close - spread,
        "close": close,
        "volume": 1000,
        "vwap": None,
    }


def test_bars_frame_sorts_dedupes_and_dates():
    bars = [_bar(2, 102.0), _bar(0, 100.0), _bar(1, 101.0), _bar(2, 103.0)]
    df = bars_frame(bars)
    assert list(df["close"]) == [100.0, 101.0, 103.0]  # dedup keeps last
    assert df["as_of"].iloc[0].isoformat() == "2020-01-01"


def test_bars_frame_empty():
    assert bars_frame([]).empty


def test_z_band_label_boundaries():
    assert z_band_label(0.0) == "NEUTRAL"
    assert z_band_label(0.5) == "MILD HIGH"  # lo-inclusive
    assert z_band_label(-2.5) == "DEEPLY OVERSOLD"
    assert z_band_label(2.0) == "DEEPLY OVERBOUGHT"
    assert z_band_label(None) is None
    assert z_band_label(float("nan")) is None


def test_z_vs_200dma_flat_then_jump():
    # 400 flat closes, then a step: distance from the 200DMA is positive,
    # z is positive and finite.
    close = pd.Series([100.0] * 400 + [110.0] * 30)
    z = z_vs_200dma(close)
    assert math.isfinite(float(z.iloc[-1]))
    assert float(z.iloc[-1]) > 1.0
    assert pd.isna(z.iloc[100])  # not enough history yet


def test_sma200_slope_ann_constant_growth():
    # close grows exactly 0.05%/day => sma200 grows 0.05%/day once warm;
    # annualized = 1.0005^252 - 1.
    close = pd.Series([100.0 * (1.0005**i) for i in range(500)])
    s = sma200_slope_ann(close)
    assert float(s.iloc[-1]) == pytest.approx(1.0005**252 - 1.0, rel=1e-3)


def test_slope_regime_labels():
    assert slope_regime(0.15) == "STRONG UPTREND"
    assert slope_regime(0.05) == "UPTREND"
    assert slope_regime(0.0) == "FLAT"
    assert slope_regime(-0.05) == "DOWNTREND"
    assert slope_regime(-0.15) == "STRONG DOWNTREND"
    assert slope_regime(None) is None


def test_rsi14_all_up_saturates_high():
    close = pd.Series([100.0 + i for i in range(50)])
    r = rsi14(close)
    assert float(r.iloc[-1]) > 95.0


def test_ma_kinematics_uptrend_alignment():
    bars = [_bar(i, 100.0 * (1.001**i)) for i in range(300)]
    df = bars_frame(bars)
    kin = ma_kinematics(df)
    assert kin["alignment"] == 3  # close > sma20 > sma50 > sma200
    assert kin["sma20"]["slope_atr"] > 0
    assert kin["sma200"]["tstat"] > 0


def test_last_pivot_index_v_shape():
    # 100 up-days, 100 down-days, 100 up-days: last confirmed pivot is the
    # trough near index 199 (zigzag confirms after a k*ATR reversal).
    closes = (
        [100.0 + i for i in range(100)]
        + [199.0 - i for i in range(100)]
        + [100.0 + i for i in range(100)]
    )
    bars = [_bar(i, c) for i, c in enumerate(closes)]
    piv = last_pivot_index(bars_frame(bars))
    assert 190 <= piv <= 205


def test_fit_sigmoid_on_synthetic_s_curve():
    t = np.arange(120, dtype=float)
    closes = 100.0 + 100.0 / (1.0 + np.exp(-0.15 * (t - 60.0)))
    out = fit_sigmoid(closes)
    assert out["valid"] is True
    assert out["r2_sigmoid"] > out["r2_linear"]
    assert out["k"] == pytest.approx(0.15, abs=0.03)
    # t_now=119, t0≈60 => s = k*(119-60) ≈ 8.85 => SATURATED
    assert out["phase"] == "SATURATED"


def test_fit_sigmoid_exposes_fitted_curve_when_valid():
    # A valid fit ships the actual segment + the fitted logistic so the UI can
    # draw actual-vs-fit (no fabrication — these are the real fitted values).
    t = np.arange(120, dtype=float)
    closes = 100.0 + 100.0 / (1.0 + np.exp(-0.15 * (t - 60.0)))
    out = fit_sigmoid(closes)
    assert out["valid"] is True
    assert out["actual"] == pytest.approx(closes.tolist(), abs=1e-6)
    assert len(out["fit"]) == len(closes)
    assert out["fit"][0] < out["fit"][-1]  # monotone rising fit


def test_fit_sigmoid_rejects_linear_series():
    closes = np.array([100.0 + 0.5 * i for i in range(120)])
    out = fit_sigmoid(closes)
    assert out["valid"] is False  # beats-linear guard: no S-curve structure
    # nothing to chart when the fit is rejected -> UI leaves the panel blank
    assert out.get("fit") is None
    assert out.get("actual") is None


def test_fit_sigmoid_too_short():
    assert fit_sigmoid(np.array([100.0, 101.0]))["valid"] is False


def test_forward_return_table_hand_verified():
    # ⭐ Money path. 12 closes; horizon 2. Injected z assigns:
    #  - sessions 0..3  -> z=0.0  (NEUTRAL)
    #  - sessions 4..7  -> z=1.7  (OVERBOUGHT)
    #  - sessions 8..11 -> z=-1.7 (OVERSOLD)   (no forward bar at h=2 for 10,11)
    closes = pd.Series(
        [100.0, 110.0, 99.0, 105.0, 100.0, 100.0, 90.0, 95.0, 100.0, 100.0, 105.0, 95.0]
    )
    z = pd.Series([0.0] * 4 + [1.7] * 4 + [-1.7] * 4)
    rows = forward_return_table(closes, z, horizons=(2,))
    by_band = {r["band"]: r for r in rows}

    # NEUTRAL fwd 2d: 99/100-1=-0.01, 105/110-1=-0.045454..,
    #                 100/99-1=+0.010101.., 100/105-1=-0.047619..
    neutral = by_band["NEUTRAL"]
    assert neutral["count"] == 4
    assert neutral["mean"] == pytest.approx(
        (-0.01 - 0.0454545454 + 0.0101010101 - 0.0476190476) / 4, abs=1e-9
    )
    assert neutral["win_rate"] == pytest.approx(0.25)  # only +0.0101 wins

    # OVERBOUGHT fwd 2d from closes 100,100,90,95 -> 90/100-1=-0.10,
    #  95/100-1=-0.05, 100/90-1=+0.111111.., 100/95-1=+0.0526315789
    ob = by_band["OVERBOUGHT"]
    assert ob["count"] == 4
    assert ob["median"] == pytest.approx((-0.05 + 0.0526315789) / 2, abs=1e-9)
    assert ob["win_rate"] == pytest.approx(0.5)

    # OVERSOLD: sessions 8,9 have forward bars (105/100-1, 95/100-1);
    # 10,11 fall off the end and MUST be excluded (look-ahead discipline).
    osold = by_band["OVERSOLD"]
    assert osold["count"] == 2
    assert osold["mean"] == pytest.approx((0.05 - 0.05) / 2, abs=1e-12)


def test_forward_return_table_empty_bands_omitted():
    closes = pd.Series([100.0, 101.0, 102.0, 103.0])
    z = pd.Series([0.0, 0.0, 0.0, 0.0])
    rows = forward_return_table(closes, z, horizons=(1,))
    assert {r["band"] for r in rows} == {"NEUTRAL"}


def test_forward_return_table_drops_non_finite():
    # A zero close makes fwd = shift(-h)/0 -> inf; it must not poison the stats.
    closes = pd.Series([100.0, 0.0, 102.0, 103.0, 104.0])
    z = pd.Series([0.0, 0.0, 0.0, 0.0, 0.0])
    rows = forward_return_table(closes, z, horizons=(1,))
    assert rows, "expected at least one band row"
    for r in rows:
        assert math.isfinite(r["mean"])
        assert math.isfinite(r["median"])
        assert 0.0 <= r["win_rate"] <= 1.0


def test_relative_strength_outperforming():
    bars = [_bar(i, 100.0 * (1.002**i)) for i in range(300)]
    spy = [_bar(i, 100.0 * (1.0005**i)) for i in range(300)]
    rs = relative_strength(bars_frame(bars), bars_frame(spy))
    assert rs["trend"] == "OUTPERFORMING"
    assert rs["ratio"] > rs["ma60"] > rs["ma200"]


def test_composite_score_bounded_and_none_safe():
    assert composite_score(
        alignment=3, slope_tstat_200=10.0, macd_hist_atr=5.0, rsi_z=4.0
    ) == pytest.approx(1.0, abs=0.05)
    assert (
        composite_score(
            alignment=None, slope_tstat_200=None, macd_hist_atr=None, rsi_z=None
        )
        is None
    )


def test_build_technical_snapshot_thin_history_returns_none():
    bars = [_bar(i, 100.0 + i * 0.1) for i in range(150)]
    assert build_technical_snapshot(bars) is None


def test_build_technical_snapshot_full():
    bars = [
        _bar(i, 100.0 * (1.0008**i) * (1 + 0.01 * math.sin(i / 7))) for i in range(500)
    ]
    spy = [_bar(i, 100.0 * (1.0004**i)) for i in range(500)]
    snap = build_technical_snapshot(bars, spy)
    assert snap is not None
    assert snap["bars_n"] == 500
    assert snap["z_band"] in {label for _, _, label in Z_BANDS}
    assert isinstance(snap["forward_returns"], list) and snap["forward_returns"]
    assert {r["horizon"] for r in snap["forward_returns"]} <= {20, 40, 60}
    series = build_technical_series(bars, spy)
    assert list(series.columns) == [
        "as_of",
        "close",
        "sma20",
        "sma50",
        "sma200",
        "z_vs_200dma",
        "z_band",
        "sma200_slope_ann",
        "slope_regime",
        "rsi14",
        "macd_hist_atr",
        "fast_macd_hist_atr",
        "slow_macd_hist_atr",
        "fast_macd_delta",
        "slow_macd_delta",
        "fast_macd_delta2",
        "fast_macd_norm",
        "slow_macd_norm",
        "rv20",
        "rv20_z",
        "vol_of_vol",
        "skew60",
        "kurt60",
        "jerk20",
        "rsi_z",
        "rsi_slope5",
        "macd_slope3",
        "kin_slope20",
        "kin_slope50",
        "kin_slope200",
        "alignment",
        "rs_ratio",
    ]
    assert len(series) == 500
    # Derived metric history is populated and finite on a long series.
    last = series.iloc[-1]
    for col in ("rv20", "rv20_z", "skew60", "kurt60", "rsi_z", "kin_slope200"):
        assert math.isfinite(float(last[col])), col
    assert last["alignment"] in {-3, -2, -1, 0, 1, 2, 3}
