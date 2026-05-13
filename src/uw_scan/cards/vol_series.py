"""Pure pandas-based derivers for the Volatility Tab v2 series.

Each function takes plain dict rows (whatever the repo returned) and returns a
pandas DataFrame with named columns. No DB access, no IO. The orchestrator
(`reports/volatility_series.py`) handles persistence.
"""

from __future__ import annotations

import logging
import math

import pandas as pd

log = logging.getLogger(__name__)


def compute_vrp_series(
    rv_rows: list[dict],
    *,
    window: int = 20,
) -> pd.DataFrame:
    """Daily VRP = IV - RV with a `window`-day rolling z-score.

    Input rows: `market_date`, `implied_volatility`, `realized_volatility`.
    Output cols: `market_date`, `iv`, `rv`, `vrp`, `vrp_z_20`.
    """
    df = pd.DataFrame(rv_rows)
    if df.empty:
        return pd.DataFrame(columns=["market_date", "iv", "rv", "vrp", "vrp_z_20"])
    df = df.rename(
        columns={
            "implied_volatility": "iv",
            "realized_volatility": "rv",
        }
    )[["market_date", "iv", "rv"]]
    df["iv"] = pd.to_numeric(df["iv"], errors="coerce")
    df["rv"] = pd.to_numeric(df["rv"], errors="coerce")
    df["vrp"] = df["iv"] - df["rv"]
    rolling = df["vrp"].rolling(window, min_periods=window)
    mean = rolling.mean()
    std = rolling.std()  # ddof=1 — finance convention.
    df["vrp_z_20"] = (df["vrp"] - mean) / std.replace(0, float("nan"))
    return df


def compute_iv_of_iv(
    rv_rows: list[dict],
    *,
    window: int = 20,
) -> pd.DataFrame:
    """Annualised rolling stdev of daily IV — per-stock VVIX analogue.

    Output cols: `market_date`, `iv`, `iv_of_iv_20`.
    """
    df = pd.DataFrame(rv_rows)
    if df.empty:
        return pd.DataFrame(columns=["market_date", "iv", "iv_of_iv_20"])
    df = df.rename(columns={"implied_volatility": "iv"})[["market_date", "iv"]]
    df["iv"] = pd.to_numeric(df["iv"], errors="coerce")
    rolling = df["iv"].rolling(window, min_periods=window).std()
    df["iv_of_iv_20"] = rolling * math.sqrt(252)
    return df


def compute_rvol_and_percentile(
    price_rows: list[dict],
    *,
    window: int = 21,
    pctile_window: int = 252,
) -> pd.DataFrame:
    """Realised vol (annualised) over `window` days + trailing percentile.

    Input rows: `market_date`, `price`.
    Output: `market_date`, `price`, `log_ret`, `rvol_21`, `rvol_pctile`.
    """
    df = pd.DataFrame(price_rows)
    if df.empty:
        return pd.DataFrame(
            columns=["market_date", "price", "log_ret", "rvol_21", "rvol_pctile"]
        )
    df = df.sort_values("market_date").reset_index(drop=True)
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df["log_ret"] = (df["price"] / df["price"].shift(1)).apply(
        lambda x: math.log(x) if x and x > 0 else float("nan")
    )
    df["rvol_21"] = df["log_ret"].rolling(window, min_periods=window).std() * math.sqrt(
        252
    )

    def _pctile(s: pd.Series) -> float:
        clean = s.dropna()
        if len(clean) < 2:
            return float("nan")
        cur = clean.iloc[-1]
        rank = (clean < cur).sum() + 0.5 * (clean == cur).sum()
        return 100.0 * rank / len(clean)

    df["rvol_pctile"] = (
        df["rvol_21"]
        .rolling(pctile_window, min_periods=window)
        .apply(_pctile, raw=False)
    )
    return df


def compute_stock_spy_corr(
    stock_price_rows: list[dict],
    spy_ohlc_rows: list[dict],
    *,
    window: int = 21,
) -> pd.DataFrame:
    """Pearson correlation between stock log-returns and SPY log-returns.

    Returns are computed per symbol on its own calendar first, then merged by
    date so the correlation only consumes pairs of true single-day returns.

    Stock rows: `market_date`, `price`. SPY rows: `market_date`, `close`.
    Output: `market_date`, `spy_corr_21`.
    """
    stock = pd.DataFrame(stock_price_rows)
    spy = pd.DataFrame(spy_ohlc_rows)
    if stock.empty or spy.empty:
        return pd.DataFrame(columns=["market_date", "spy_corr_21"])

    def _log_ret(prev, curr) -> float:
        try:
            if prev is None or curr is None:
                return float("nan")
            p = float(prev)
            c = float(curr)
        except (TypeError, ValueError) as exc:
            log.debug("log-return coercion skipped: %s", repr(exc))
            return float("nan")
        if not (p > 0 and c > 0):
            return float("nan")
        return math.log(c / p)

    stock = stock.sort_values("market_date").reset_index(drop=True)
    stock["price"] = pd.to_numeric(stock["price"], errors="coerce")
    stock["stock_ret"] = [
        _log_ret(p, c)
        for p, c in zip([None, *stock["price"].iloc[:-1]], stock["price"])
    ]

    spy = spy.sort_values("market_date").reset_index(drop=True)
    spy["close"] = pd.to_numeric(spy["close"], errors="coerce")
    spy["spy_ret"] = [
        _log_ret(p, c) for p, c in zip([None, *spy["close"].iloc[:-1]], spy["close"])
    ]

    df = (
        stock[["market_date", "stock_ret"]]
        .merge(spy[["market_date", "spy_ret"]], on="market_date", how="inner")
        .sort_values("market_date")
        .reset_index(drop=True)
    )
    df["spy_corr_21"] = (
        df["stock_ret"].rolling(window, min_periods=window).corr(df["spy_ret"])
    )
    return df[["market_date", "spy_corr_21"]]


def classify_regime_state(
    *,
    rvol_pctile: float,
    spy_corr_21: float,
    median_corr: float | None,
) -> str:
    """One of GOLDILOCKS / FRAGILE_CALM / STOCK_PICKER / SYSTEMIC_PANIC.

    `median_corr=None` (no 252d history yet) falls back to a market-wide
    median of 0.5 per spec §11 cold-start note.
    """
    cutoff = 0.5 if median_corr is None else median_corr
    low_vol = rvol_pctile < 50
    low_corr = spy_corr_21 < cutoff
    if low_vol and low_corr:
        return "GOLDILOCKS"
    if low_vol and not low_corr:
        return "FRAGILE_CALM"
    if not low_vol and low_corr:
        return "STOCK_PICKER"
    return "SYSTEMIC_PANIC"


def compute_iv_rv_z_overlay(
    rv_rows: list[dict],
    *,
    window: int = 20,
) -> pd.DataFrame:
    """Per-day z-score of IV and RV vs their own trailing `window`.

    Output: `market_date`, `iv_z`, `rv_z`.
    """
    df = pd.DataFrame(rv_rows)
    if df.empty:
        return pd.DataFrame(columns=["market_date", "iv_z", "rv_z"])
    df = df.rename(columns={"implied_volatility": "iv", "realized_volatility": "rv"})[
        ["market_date", "iv", "rv"]
    ]
    df["iv"] = pd.to_numeric(df["iv"], errors="coerce")
    df["rv"] = pd.to_numeric(df["rv"], errors="coerce")

    def _z(s: pd.Series) -> pd.Series:
        r = s.rolling(window, min_periods=window)
        return (s - r.mean()) / r.std().replace(0, float("nan"))

    df["iv_z"] = _z(df["iv"])
    df["rv_z"] = _z(df["rv"])
    return df[["market_date", "iv_z", "rv_z"]]
