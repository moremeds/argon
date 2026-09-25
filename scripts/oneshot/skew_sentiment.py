#!/usr/bin/env python3
"""Can skew be used as a sentiment / trend gauge (not a return predictor)?

The return-prediction angle failed (skew is beta/momentum, ~0 predictive IC). But a
*sentiment thermometer* has a different job: reliably REFLECT the market's current
fear/positioning state and its trend. Being beta is a point in favor of that use, not
against. And single-name rr_25d is noisy (0-DTE instability), but the cross-sectional
AVERAGE across ~87 names should wash that out into a smooth aggregate.

Builds a daily aggregate skew-sentiment series over single names and asks:
  1. persistence  — is it smooth/autocorrelated enough to call a "trend"? (vs noise)
  2. coincident   — does it move WITH contemporaneous market stress? (thermometer validity)
  3. lead vs lag  — does the skew trend lead price, coincide, or lag?
  4. extremes     — at fear extremes, is the forward market move trend-follow or contrarian?

Aggregates: mean rr_z_180d (standardized skew stress) and net-fear breadth
(%PANIC − %CHASE). Market proxy = SPY (fallback QQQ) close from realized_volatility_history.
Read-only.

Reproduce:
    export PGPASSWORD=... UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard
    uv run --directory /Users/chenxi/projects/argon \
        python .worktrees/skew-directional-probe/scripts/oneshot/skew_sentiment.py
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg

FWD, PAST = 20, 20
OUT = Path(__file__).resolve().parents[2] / "docs" / "research" / "skew-directional"


def _dsn() -> str:
    pw = os.environ.get("PGPASSWORD") or os.environ.get("UW_SCAN_DB_PASSWORD")
    if not pw:
        raise SystemExit("set PGPASSWORD — no secret is stored in this file")
    host = os.environ.get("UW_SCAN_DB_HOST", "100.66.147.98")
    name = os.environ.get("UW_SCAN_DB_NAME", "option_wizard")
    return f"host={host} port=5432 dbname={name} user=argon_app password={pw}"


def _load() -> pd.DataFrame:
    with psycopg.connect(_dsn()) as conn:
        snap = pd.DataFrame(
            conn.execute(
                """SELECT market_date, rr_z_180d, drive_class
               FROM uw_scan.skew_analytics_snapshot
               WHERE basis='eod' AND asset_class='single_name'"""
            ).fetchall(),
            columns=["market_date", "rr_z", "drive"],
        )
        mkt = pd.DataFrame(
            conn.execute(
                """SELECT ticker, market_date, price FROM uw_scan.realized_volatility_history
               WHERE ticker IN ('SPY','QQQ')"""
            ).fetchall(),
            columns=["ticker", "market_date", "price"],
        )
    snap["rr_z"] = pd.to_numeric(snap["rr_z"], errors="coerce")
    # aggregate daily sentiment across single names
    agg = (
        snap.groupby("market_date")
        .agg(
            mean_rrz=("rr_z", "mean"),
            panic=("drive", lambda s: (s == "PANIC").mean()),
            chase=("drive", lambda s: (s == "CHASE").mean()),
            n=("drive", "size"),
        )
        .reset_index()
    )
    agg["net_fear"] = agg["panic"] - agg["chase"]

    mkt["price"] = pd.to_numeric(mkt["price"], errors="coerce")
    proxy = "SPY" if (mkt.ticker == "SPY").any() else "QQQ"
    m = mkt[mkt.ticker == proxy].dropna(subset=["price"]).sort_values("market_date")
    m["r_fwd"] = m["price"].shift(-FWD) / m["price"] - 1.0
    m["r_past"] = m["price"] / m["price"].shift(PAST) - 1.0
    m["r_1d"] = m["price"].pct_change()
    df = agg.merge(
        m[["market_date", "r_fwd", "r_past", "r_1d"]], on="market_date", how="inner"
    )
    df.attrs["proxy"] = proxy
    return df.sort_values("market_date").reset_index(drop=True)


def _corr(a: pd.Series, b: pd.Series) -> tuple[float, int]:
    d = pd.concat([a, b], axis=1).dropna()
    if len(d) < 10:
        return (float("nan"), len(d))
    return (float(d.iloc[:, 0].corr(d.iloc[:, 1])), len(d))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    df = _load()
    print(
        f"{len(df)} days {df.market_date.min()}..{df.market_date.max()}, "
        f"market proxy={df.attrs['proxy']}, avg {df.n.mean():.0f} names/day"
    )

    print("\n=== 1. persistence (autocorrelation) — is it a smooth trend or noise? ===")
    for col in ["mean_rrz", "net_fear"]:
        ac = {lag: round(df[col].autocorr(lag), 3) for lag in (1, 5, 20)}
        print(f"  {col:9s} autocorr  lag1={ac[1]}  lag5={ac[5]}  lag20={ac[20]}")

    print("\n=== 2/3. coincident vs leading vs lagging (corr with market return) ===")
    df["d_rrz"] = df["mean_rrz"].diff()
    df["d_fear"] = df["net_fear"].diff()
    rows = []
    for name, s in [
        ("mean_rrz level", df.mean_rrz),
        ("net_fear level", df.net_fear),
        ("Δmean_rrz", df.d_rrz),
        ("Δnet_fear", df.d_fear),
    ]:
        c_past, _ = _corr(s, df.r_past)  # vs TRAILING return -> coincident/lagging
        c_fwd, n = _corr(s, df.r_fwd)  # vs FORWARD return  -> leading (predictive)
        rows.append(
            {
                "sentiment": name,
                "corr_vs_trailing20d": round(c_past, 3),
                "corr_vs_forward20d": round(c_fwd, 3),
                "n": n,
            }
        )
    tbl = pd.DataFrame(rows)
    print(tbl.to_string(index=False))
    tbl.to_csv(OUT / "sentiment_leadlag.csv", index=False)
    print(
        "  (strong negative vs TRAILING = valid coincident fear thermometer;\n"
        "   ~0 vs FORWARD = not leading/predictive — reflects, doesn't forecast)"
    )

    print(
        "\n=== 4. fear extremes -> forward 20d market move (contrarian vs trend?) ==="
    )
    df["fear_q"] = pd.qcut(df["net_fear"].rank(method="first"), 5, labels=False)
    ext = (
        df.groupby("fear_q")
        .agg(
            days=("r_fwd", "size"),
            net_fear=("net_fear", "mean"),
            mkt_fwd20=("r_fwd", "mean"),
            mkt_trail20=("r_past", "mean"),
        )
        .round(4)
    )
    print(ext.to_string())
    df.to_csv(OUT / "sentiment_series.csv", index=False)
    print(f"\nwrote CSVs to {OUT}")


def _selfcheck() -> None:
    # _corr is the load-bearing helper: perfect anti-correlation, and the <10-pt guard.
    a = pd.Series(np.arange(1.0, 21.0))
    neg, _ = _corr(a, -a)
    pos, n = _corr(a, 2 * a + 1)
    assert abs(neg + 1.0) < 1e-9, neg
    assert abs(pos - 1.0) < 1e-9 and n == 20, (pos, n)
    short, ns = _corr(pd.Series([1.0, 2, 3]), pd.Series([1.0, 2, 3]))
    assert np.isnan(short) and ns == 3, (
        short,
        ns,
    )  # too few points -> nan, not a spurious 1.0
    print("selfcheck ok")


if __name__ == "__main__":
    import sys

    _selfcheck() if "--selfcheck" in sys.argv else main()
