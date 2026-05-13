"""Unit tests for the Volatility Tab v2 derivers (spec 2026-05-13)."""

from __future__ import annotations

import math
from datetime import date, timedelta

import pandas as pd
import pytest

from uw_scan.cards.vol_series import (
    classify_regime_state,
    compute_iv_of_iv,
    compute_iv_rv_z_overlay,
    compute_rvol_and_percentile,
    compute_stock_spy_corr,
    compute_vrp_series,
)

# -------------------- compute_vrp_series ------------------------------------


def test_compute_vrp_series_basic():
    # Use values that produce exact-zero VRP diffs to avoid the float-precision
    # trap where 0.50-0.40 ≠ 0.52-0.42 by ~1e-17.
    rv_rows = [
        {
            "market_date": date(2026, 1, 1),
            "implied_volatility": 0.50,
            "realized_volatility": 0.50,
        },
        {
            "market_date": date(2026, 1, 2),
            "implied_volatility": 0.50,
            "realized_volatility": 0.50,
        },
        {
            "market_date": date(2026, 1, 3),
            "implied_volatility": 0.65,
            "realized_volatility": 0.50,
        },
    ]
    df = compute_vrp_series(rv_rows, window=2)
    assert list(df["vrp"]) == pytest.approx([0.0, 0.0, 0.15])
    # iloc[0]: no window → NaN. iloc[1]: [0,0] std=0 → NaN.
    # iloc[2]: [0, 0.15] mean=0.075, sample stdev=0.10607, z≈0.7071.
    assert pd.isna(df["vrp_z_20"].iloc[0])
    assert pd.isna(df["vrp_z_20"].iloc[1])
    assert float(df["vrp_z_20"].iloc[2]) == pytest.approx(0.7071, abs=0.01)


def test_compute_vrp_series_handles_missing():
    rv_rows = [
        {
            "market_date": date(2026, 1, 1),
            "implied_volatility": None,
            "realized_volatility": 0.40,
        },
        {
            "market_date": date(2026, 1, 2),
            "implied_volatility": 0.52,
            "realized_volatility": None,
        },
    ]
    df = compute_vrp_series(rv_rows, window=2)
    assert pd.isna(df["vrp"].iloc[0])
    assert pd.isna(df["vrp"].iloc[1])


def test_compute_vrp_series_empty():
    df = compute_vrp_series([])
    assert df.empty
    assert list(df.columns) == ["market_date", "iv", "rv", "vrp", "vrp_z_20"]


# -------------------- compute_iv_of_iv --------------------------------------


def test_iv_of_iv_annualisation():
    rv_rows = [
        {
            "market_date": date(2026, 1, 1) + timedelta(days=d - 1),
            "implied_volatility": 0.50,
        }
        for d in range(1, 22)
    ]
    rv_rows[-1]["implied_volatility"] = 0.60
    df = compute_iv_of_iv(rv_rows, window=20)
    last = float(df["iv_of_iv_20"].iloc[-1])
    # mean = 0.505; ddof=1 stdev of 20 values where 19 are 0.50 and one is
    # 0.60 → sqrt((19*(0.005)^2 + (0.095)^2) / 19) ≈ 0.02236.
    # Annualised: 0.02236 × sqrt(252) ≈ 0.3550.
    assert last == pytest.approx(0.02236 * math.sqrt(252), abs=0.001)


def test_iv_of_iv_short_series_returns_nan():
    rv_rows = [
        {"market_date": date(2026, 1, d), "implied_volatility": 0.5}
        for d in range(1, 5)
    ]
    df = compute_iv_of_iv(rv_rows, window=20)
    assert pd.isna(df["iv_of_iv_20"].iloc[-1])


# -------------------- compute_rvol_and_percentile ---------------------------


def _price_rows(prices: list[float]) -> list[dict]:
    base = date(2026, 1, 1)
    return [
        {"market_date": base + timedelta(days=i), "price": p}
        for i, p in enumerate(prices)
    ]


def test_rvol_basic():
    prices = [100 + i * 0.5 for i in range(22)]
    prices[-1] = 105.0
    df = compute_rvol_and_percentile(_price_rows(prices), window=21)
    assert pd.notna(df["rvol_21"].iloc[-1])
    assert float(df["rvol_21"].iloc[-1]) > 0


def test_rvol_percentile_bounds():
    prices = [100.0] * 250 + [100.0, 110.0]
    df = compute_rvol_and_percentile(_price_rows(prices), window=21, pctile_window=252)
    last = float(df["rvol_pctile"].iloc[-1])
    assert 50 <= last <= 100


def test_rvol_short_series_returns_nan():
    df = compute_rvol_and_percentile(_price_rows([100, 101, 102]), window=21)
    assert pd.isna(df["rvol_21"].iloc[-1])
    assert pd.isna(df["rvol_pctile"].iloc[-1])


# -------------------- compute_stock_spy_corr --------------------------------


def test_corr_perfectly_correlated():
    base = date(2026, 1, 1)
    stock = [
        {"market_date": base + timedelta(days=i), "price": 100 + i * 0.5}
        for i in range(30)
    ]
    spy = [
        {"market_date": base + timedelta(days=i), "close": 500 + i * 2.5}
        for i in range(30)
    ]
    df = compute_stock_spy_corr(stock, spy, window=21)
    last = float(df["spy_corr_21"].iloc[-1])
    assert last == pytest.approx(1.0, abs=0.001)


def test_corr_missing_spy_row_in_middle():
    base = date(2026, 1, 1)
    stock = [
        {"market_date": base + timedelta(days=i), "price": 100 + i * 0.5}
        for i in range(25)
    ]
    spy = [
        {"market_date": base + timedelta(days=i), "close": 500 + i * 2.5}
        for i in range(25)
    ]
    spy.pop(10)
    df = compute_stock_spy_corr(stock, spy, window=21)
    assert pd.notna(df["spy_corr_21"].iloc[-1])


# -------------------- classify_regime_state ---------------------------------


def test_classify_all_four_states():
    m = 0.4
    assert (
        classify_regime_state(rvol_pctile=20, spy_corr_21=0.1, median_corr=m)
        == "GOLDILOCKS"
    )
    assert (
        classify_regime_state(rvol_pctile=20, spy_corr_21=0.7, median_corr=m)
        == "FRAGILE_CALM"
    )
    assert (
        classify_regime_state(rvol_pctile=80, spy_corr_21=0.1, median_corr=m)
        == "STOCK_PICKER"
    )
    assert (
        classify_regime_state(rvol_pctile=80, spy_corr_21=0.7, median_corr=m)
        == "SYSTEMIC_PANIC"
    )


def test_classify_cold_start_falls_back_to_0_5():
    assert (
        classify_regime_state(rvol_pctile=20, spy_corr_21=0.6, median_corr=None)
        == "FRAGILE_CALM"
    )
    assert (
        classify_regime_state(rvol_pctile=20, spy_corr_21=0.4, median_corr=None)
        == "GOLDILOCKS"
    )


# -------------------- compute_iv_rv_z_overlay -------------------------------


def test_iv_rv_z_overlay_populated():
    rv_rows = [
        {
            "market_date": date(2026, 1, 1) + timedelta(days=d),
            "implied_volatility": 0.50 + (d % 3) * 0.02,
            "realized_volatility": 0.40 + (d % 3) * 0.01,
        }
        for d in range(25)
    ]
    df = compute_iv_rv_z_overlay(rv_rows, window=20)
    assert "iv_z" in df.columns and "rv_z" in df.columns
    assert pd.notna(df["iv_z"].iloc[-1])
