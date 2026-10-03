#!/usr/bin/env python3
"""Track 1 — validate the skew *directional* verdict on the 14 months already banked.

The /stock Skew tab verdict is a lookup into ``skew_directional_verdicts``: each day
the engine classifies a ticker into ``(asset_class, deviation_class, drive_class)`` and
reports that bucket's historical mean T+20 forward return (``forward_sep``, e.g. QQQ's
"-5.3%/20d"). That number is an *in-sample* conditional mean: the directional layer has
no walk-forward holdout (its RV sibling does), persists no dispersion/t-stat, and its
forward returns overlap heavily. This script reproduces the number and then applies the
rigor the engine skips:

  reproduce  -> universe-demeaned bucket sep (matches the engine's method)
  neutralize -> also demean vs the same-asset_class pool (strips shared index/sector beta)
  OOS        -> IS (<2026-02-01) vs OOS (>=) bucket sep, + per-quarter stability
  overlap    -> non-overlapping (>=20 trading-day-spaced, per ticker) effective-n + t-stat
  breakout   -> per-ticker decomposition of the key buckets (is it one name or the pool?)

Read-only. No writes to prod tables. Covers index_macro AND single_name (+ sector_etf,
credit) so the single-stock verdict is validated alongside the index one.

Reproduce (password via env, never hardcoded):
    export PGPASSWORD=... UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard
    uv run --directory /Users/chenxi/projects/argon \
        python .worktrees/skew-directional-probe/scripts/oneshot/skew_directional_validate.py
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg

HORIZON = 20  # trading days forward — matches skew_markout.HORIZON
MOM_WINDOW = 63  # trailing trading days for the price-momentum control (~3 months)
OOS_SPLIT = "2026-02-01"
MIN_N = 20  # bucket reporting floor — matches skew_markout.min_n
OUT = Path(__file__).resolve().parents[2] / "docs" / "research" / "skew-directional"


def _dsn() -> str:
    host = os.environ.get("UW_SCAN_DB_HOST", "100.66.147.98")
    name = os.environ.get("UW_SCAN_DB_NAME", "option_wizard")
    user = os.environ.get("UW_SCAN_DB_USER", "argon_app")
    port = os.environ.get("UW_SCAN_DB_PORT", "5432")
    pw = os.environ.get("PGPASSWORD") or os.environ.get("UW_SCAN_DB_PASSWORD")
    if not pw:
        raise SystemExit(
            "set PGPASSWORD (or UW_SCAN_DB_PASSWORD) — no secret is stored in this file"
        )
    return f"host={host} port={port} dbname={name} user={user} password={pw}"


def _load() -> pd.DataFrame:
    """Snapshot classifications joined to T+20 forward returns from realized_volatility_history."""
    with psycopg.connect(_dsn()) as conn:
        snap = pd.DataFrame(
            conn.execute(
                """SELECT ticker, market_date, asset_class, deviation_class, drive_class,
                          borrow_flag, directional_lean, lean_confidence, spot
                   FROM uw_scan.skew_analytics_snapshot WHERE basis='eod'"""
            ).fetchall(),
            columns=[
                "ticker",
                "market_date",
                "asset_class",
                "deviation_class",
                "drive_class",
                "borrow_flag",
                "directional_lean",
                "lean_confidence",
                "spot",
            ],
        )
        rvh = pd.DataFrame(
            conn.execute(
                "SELECT ticker, market_date, price FROM uw_scan.realized_volatility_history"
            ).fetchall(),
            columns=["ticker", "market_date", "price"],
        )

    rvh["price"] = pd.to_numeric(rvh["price"], errors="coerce")
    rvh = rvh.dropna(subset=["price"]).sort_values(["ticker", "market_date"])
    # positional 20-trading-day forward return per ticker (engine convention)
    rvh["fwd_price"] = rvh.groupby("ticker")["price"].shift(-HORIZON)
    rvh["day_ix"] = rvh.groupby(
        "ticker"
    ).cumcount()  # per-ticker trading-day index for overlap
    rvh["fwd_ret"] = rvh["fwd_price"] / rvh["price"] - 1.0
    # trailing momentum known AT decision time t (backward window, no lookahead)
    rvh["mom"] = rvh["price"] / rvh.groupby("ticker")["price"].shift(MOM_WINDOW) - 1.0

    df = snap.merge(
        rvh[["ticker", "market_date", "fwd_ret", "day_ix", "mom"]],
        on=["ticker", "market_date"],
        how="inner",
    )
    df = df.dropna(subset=["fwd_ret"])
    df["borrow_clean"] = ~df["borrow_flag"].fillna("").str.contains("hard", case=False)

    # neutralizations: excess forward return removing a common component on each date
    df["exc_univ"] = df["fwd_ret"] - df.groupby("market_date")["fwd_ret"].transform(
        "mean"
    )
    df["exc_pool"] = df["fwd_ret"] - df.groupby(["market_date", "asset_class"])[
        "fwd_ret"
    ].transform("mean")
    # momentum + beta neutralization: excess vs same-date, same-momentum-decile names.
    # If the CHASE (up-momentum) edge survives this, it is skew-specific, not the
    # momentum factor. Deciles per date across all names with a defined trailing return.
    md = df.dropna(subset=["mom"]).copy()
    md["mom_decile"] = md.groupby("market_date")["mom"].transform(
        lambda s: (
            pd.qcut(s.rank(method="first"), 10, labels=False)
            if s.notna().sum() >= 10
            else -1
        )
    )
    md["exc_mom"] = md["fwd_ret"] - md.groupby(["market_date", "mom_decile"])[
        "fwd_ret"
    ].transform("mean")
    df = df.merge(
        md[["ticker", "market_date", "exc_mom", "mom_decile"]],
        on=["ticker", "market_date"],
        how="left",
    )
    df["quarter"] = pd.PeriodIndex(pd.to_datetime(df["market_date"]), freq="Q").astype(
        str
    )
    return df


def _nonoverlap_stats(g: pd.DataFrame, col: str) -> tuple[float, int, float]:
    """Greedy per-ticker non-overlapping (>=HORIZON apart) subsample -> (mean, eff_n, t).

    The engine's n counts every daily firing; consecutive firings share ~95% of their
    20-day forward window, so that n massively overstates independence. Keep only firings
    spaced >=HORIZON trading days apart *within each ticker*, then pool.
    """
    keep = []
    for _, sub in g.sort_values(["ticker", "day_ix"]).groupby("ticker"):
        last = -(10**9)
        for ix, val in zip(sub["day_ix"], sub[col]):
            if ix - last >= HORIZON:
                keep.append(val)
                last = ix
    arr = np.asarray(keep, dtype=float)
    eff_n = arr.size
    if eff_n < 2:
        return (float(arr.mean()) if eff_n else float("nan"), eff_n, float("nan"))
    mean = float(arr.mean())
    se = float(arr.std(ddof=1)) / np.sqrt(eff_n)
    t = mean / se if se > 0 else float("nan")
    return (mean, eff_n, t)


def _buckets(df: pd.DataFrame, sep_col: str) -> pd.DataFrame:
    rows = []
    for (ac, dev, drv), g in df.groupby(
        ["asset_class", "deviation_class", "drive_class"]
    ):
        n = len(g)
        is_g = g[g["market_date"] < pd.to_datetime(OOS_SPLIT).date()]
        oos_g = g[g["market_date"] >= pd.to_datetime(OOS_SPLIT).date()]
        no_mean, eff_n, t = _nonoverlap_stats(g, sep_col)
        rows.append(
            {
                "asset_class": ac,
                "deviation": dev,
                "drive": drv,
                "n": n,
                "sep_naive": g[sep_col].mean(),  # all firings — matches engine method
                "raw_abs": g[
                    "fwd_ret"
                ].mean(),  # undemeaned absolute fwd (directional view)
                "base_abs": df[df.asset_class == ac][
                    "fwd_ret"
                ].mean(),  # unconditional class baseline
                "hit_neg": (g[sep_col] < 0).mean(),  # fraction with negative excess fwd
                "sep_IS": is_g[sep_col].mean() if len(is_g) else float("nan"),
                "n_IS": len(is_g),
                "sep_OOS": oos_g[sep_col].mean() if len(oos_g) else float("nan"),
                "n_OOS": len(oos_g),
                "sep_nonoverlap": no_mean,
                "eff_n": eff_n,
                "t_stat": t,
            }
        )
    out = pd.DataFrame(rows).sort_values(["asset_class", "deviation", "drive"])
    return out


def _per_ticker(
    df: pd.DataFrame, ac: str, dev: str, drv: str, sep_col: str
) -> pd.DataFrame:
    g = df[
        (df.asset_class == ac) & (df.deviation_class == dev) & (df.drive_class == drv)
    ]
    rows = []
    for tkr, sub in g.groupby("ticker"):
        no_mean, eff_n, t = _nonoverlap_stats(sub, sep_col)
        rows.append(
            {
                "ticker": tkr,
                "n": len(sub),
                "sep_naive": sub[sep_col].mean(),
                "sep_nonoverlap": no_mean,
                "eff_n": eff_n,
                "t_stat": t,
            }
        )
    return pd.DataFrame(rows).sort_values("sep_naive")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    df = _load()
    clean = df[df["borrow_clean"]]  # engine verdicts are on the borrow-clean subset

    print(
        f"loaded {len(df)} ticker-days  ({df.market_date.min()} .. {df.market_date.max()}), "
        f"{df.ticker.nunique()} tickers; borrow-clean {len(clean)}"
    )

    for label, sep_col, tag in [
        ("universe-demean (reproduces engine)", "exc_univ", "univ"),
        ("pool-demean (index/sector-basis neutralized)", "exc_pool", "pool"),
        ("momentum+beta-demean (same-date same-mom-decile)", "exc_mom", "mom"),
    ]:
        src = clean.dropna(subset=[sep_col])
        tbl = _buckets(src, sep_col)
        tbl_show = tbl[tbl.n >= MIN_N].copy()
        for c in [
            "sep_naive",
            "sep_IS",
            "sep_OOS",
            "sep_nonoverlap",
            "hit_neg",
            "t_stat",
        ]:
            tbl_show[c] = tbl_show[c].round(4)
        print(f"\n===== {label} =====")
        print(tbl_show.to_string(index=False))
        tbl.to_csv(OUT / f"buckets_{tag}.csv", index=False)

    # per-ticker breakout of the buckets the /stock page actually fires from
    key = [
        ("index_macro", "NORMAL", "PANIC"),  # the QQQ screenshot bucket
        ("single_name", "NORMAL", "CHASE"),  # biggest single-name bull bucket (+6.3%)
        ("single_name", "RICH", "PANIC"),
    ]  # biggest single-name bear bucket
    frames = []
    for ac, dev, drv in key:
        pt = _per_ticker(clean, ac, dev, drv, "exc_univ")
        pt.insert(0, "bucket", f"{ac}/{dev}/{drv}")
        frames.append(pt)
        print(f"\n----- per-ticker: {ac}/{dev}/{drv} (universe-demean) -----")
        with pd.option_context("display.max_rows", 100):
            print(pt.round(4).to_string(index=False))
    pd.concat(frames).to_csv(OUT / "per_ticker_key_buckets.csv", index=False)
    print(f"\nwrote CSVs to {OUT}")


def _selfcheck() -> None:
    """Non-overlap keeps only firings >=HORIZON apart; a dense run collapses to 1 per HORIZON."""
    g = pd.DataFrame({"ticker": ["X"] * 41, "day_ix": list(range(41)), "v": [0.1] * 41})
    _, eff_n, _ = _nonoverlap_stats(g, "v")
    assert eff_n == 3, eff_n  # ix 0,20,40 -> 3 independent
    g2 = pd.DataFrame(
        {"ticker": ["A", "A", "B"], "day_ix": [0, 5, 0], "v": [0.1, 0.2, 0.3]}
    )
    _, eff_n2, _ = _nonoverlap_stats(g2, "v")
    assert eff_n2 == 2, eff_n2  # A collapses (5<20), B independent -> 2
    print("selfcheck ok")


if __name__ == "__main__":
    import sys

    if "--selfcheck" in sys.argv:
        _selfcheck()
    else:
        main()
