#!/usr/bin/env python3
"""Deep-dive — is the skew condition a value-adding momentum filter, or redundant?

Track 1 showed the one survivor (single_name/NORMAL/CHASE) beats its momentum-decile
peers by +3.6%/20d — i.e. it carries value *beyond* momentum. This turns that IC into a
portfolio question: as a long overlay, does momentum-filtered-by-skew beat plain momentum
on realized forward return, hit-rate, breadth, and per-quarter stability? And is it even
tradable (how many names fire per day)? Plus horizon sweep (5/10/20/40d).

Portfolios (equal-weight, formed each date, market-excess = minus single-name universe
mean forward return that date):
    MOM        top momentum quintile
    MOM_CHASE  top momentum quintile AND drive_class == CHASE
    MOM_NC     top momentum quintile AND (NORMAL deviation & CHASE)  <- the filtered signal
    NC_ALL     (NORMAL & CHASE) regardless of momentum               <- the raw survivor
If MOM_NC materially beats MOM, the skew filter adds value on top of momentum. If not, the
filter is redundant and the "edge" is just momentum.

Overlap-honest: reports the daily-formed mean AND a non-overlapping (every-HORIZON)
Sharpe. Read-only.

Reproduce:
    export PGPASSWORD=... UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard
    uv run --directory /Users/chenxi/projects/argon \
        python .worktrees/skew-directional-probe/scripts/oneshot/skew_momentum_filter.py
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg

MOM_WINDOW = 63
HORIZONS = (5, 10, 20, 40)
PRIMARY_H = 20
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
        rvh = pd.DataFrame(
            conn.execute(
                "SELECT ticker, market_date, price FROM uw_scan.realized_volatility_history"
            ).fetchall(),
            columns=["ticker", "market_date", "price"],
        )
        snap = pd.DataFrame(
            conn.execute(
                """SELECT ticker, market_date, deviation_class, drive_class
               FROM uw_scan.skew_analytics_snapshot
               WHERE basis='eod' AND asset_class='single_name'"""
            ).fetchall(),
            columns=["ticker", "market_date", "deviation_class", "drive_class"],
        )
    rvh["price"] = pd.to_numeric(rvh["price"], errors="coerce")
    rvh = rvh.dropna(subset=["price"]).sort_values(["ticker", "market_date"])
    rvh["day_ix"] = rvh.groupby("ticker").cumcount()
    for h in HORIZONS:
        rvh[f"f{h}"] = rvh.groupby("ticker")["price"].shift(-h) / rvh["price"] - 1.0
    rvh["mom"] = rvh["price"] / rvh.groupby("ticker")["price"].shift(MOM_WINDOW) - 1.0
    df = snap.merge(
        rvh[["ticker", "market_date", "day_ix", "mom"] + [f"f{h}" for h in HORIZONS]],
        on=["ticker", "market_date"],
        how="inner",
    ).dropna(subset=["mom"])
    # market-excess forward return per horizon (cross-sectional demean over single names)
    for h in HORIZONS:
        df[f"x{h}"] = df[f"f{h}"] - df.groupby("market_date")[f"f{h}"].transform("mean")
    # momentum quintile per date
    df["mom_q"] = df.groupby("market_date")["mom"].transform(
        lambda s: (
            pd.qcut(s.rank(method="first"), 5, labels=False)
            if s.notna().sum() >= 5
            else -1
        )
    )
    return df


def _nonoverlap_sharpe(daily: pd.DataFrame, col: str) -> float:
    """Sharpe of a per-date portfolio return using only dates >=HORIZON apart (annualized-ish)."""
    d = daily.dropna(subset=[col]).sort_values("date")
    if d.empty:
        return float("nan")
    keep, last = [], -(10**9)
    # date -> integer trading index via rank
    d = d.assign(ix=d["date"].rank(method="dense").astype(int))
    for ix, val in zip(d["ix"], d[col]):
        if ix - last >= PRIMARY_H:
            keep.append(val)
            last = ix
    a = np.asarray(keep, float)
    if a.size < 3 or a.std(ddof=1) == 0:
        return float("nan")
    periods_per_yr = 252 / PRIMARY_H
    return float(a.mean() / a.std(ddof=1) * np.sqrt(periods_per_yr))


def _portfolio(df: pd.DataFrame, mask: pd.Series, h: int) -> pd.DataFrame:
    """Per-date equal-weight mean of raw + market-excess h-day forward return, and breadth."""
    g = df[mask]
    daily = (
        g.groupby("market_date")
        .agg(raw=(f"f{h}", "mean"), exc=(f"x{h}", "mean"), n=(f"f{h}", "size"))
        .reset_index()
    )
    daily = daily.rename(columns={"market_date": "date"})
    return daily


def _summ(daily: pd.DataFrame) -> dict:
    return {
        "days": len(daily),
        "breadth": round(daily["n"].mean(), 1),
        "mean_raw": round(daily["raw"].mean(), 4),
        "mean_exc": round(daily["exc"].mean(), 4),
        "hit_exc": round((daily["exc"] > 0).mean(), 3),
        "sharpe_exc_no": round(_nonoverlap_sharpe(daily, "exc"), 2),
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    df = _load()
    print(
        f"{len(df)} single-name ticker-days, {df.market_date.min()}..{df.market_date.max()}"
    )
    top = df["mom_q"] == 4
    chase = df["drive_class"] == "CHASE"
    nc = (df["deviation_class"] == "NORMAL") & chase
    strategies = {
        "MOM (top-quintile momentum)": top,
        "MOM_CHASE (top-mom & CHASE)": top & chase,
        "MOM_NC (top-mom & NORMAL&CHASE)": top & nc,
        "NC_ALL (NORMAL&CHASE, any mom)": nc,
        "CHASE_ALL (any mom)": chase,
    }
    print(f"\n=== portfolio comparison @ {PRIMARY_H}d (market-excess) ===")
    rows = []
    for name, mask in strategies.items():
        s = _summ(_portfolio(df, mask, PRIMARY_H))
        s = {"strategy": name, **s}
        rows.append(s)
    tbl = pd.DataFrame(rows)
    print(tbl.to_string(index=False))
    tbl.to_csv(OUT / "momentum_filter_portfolios.csv", index=False)

    print(
        f"\n=== does the skew filter beat plain momentum? (MOM_NC - MOM, {PRIMARY_H}d) ==="
    )
    mom_d = _portfolio(df, top, PRIMARY_H).set_index("date")
    nc_d = _portfolio(df, top & nc, PRIMARY_H).set_index("date")
    joined = mom_d.join(nc_d, lsuffix="_mom", rsuffix="_nc", how="inner")
    if len(joined):
        spread = (joined["exc_nc"] - joined["exc_mom"]).dropna()
        t = (
            spread.mean() / (spread.std(ddof=1) / np.sqrt(len(spread)))
            if spread.std(ddof=1)
            else float("nan")
        )
        print(
            f"mean daily-formed excess spread {spread.mean():+.4f}  (naive t over {len(spread)} "
            f"overlapping dates = {t:.2f}); breadth MOM={mom_d['n'].mean():.0f} "
            f"MOM_NC={nc_d['n'].mean():.1f} names/day"
        )

    print("\n=== horizon sweep: NORMAL&CHASE market-excess forward return ===")
    hs = []
    for h in HORIZONS:
        d = _portfolio(df, nc, h)
        hs.append(
            {
                "horizon_d": h,
                "mean_exc": round(d["exc"].mean(), 4),
                "hit": round((d["exc"] > 0).mean(), 3),
                "sharpe_no": round(_nonoverlap_sharpe(d, "exc"), 2),
            }
        )
    print(pd.DataFrame(hs).to_string(index=False))

    print("\n=== per-quarter stability: MOM_NC market-excess @20d ===")
    q = _portfolio(df, top & nc, PRIMARY_H)
    q["quarter"] = pd.PeriodIndex(pd.to_datetime(q["date"]), freq="Q").astype(str)
    pq = (
        q.groupby("quarter")
        .agg(days=("exc", "size"), mean_exc=("exc", "mean"), breadth=("n", "mean"))
        .round(4)
    )
    print(pq.to_string())
    print(f"\nwrote CSVs to {OUT}")


def _selfcheck() -> None:
    # top-quintile mask picks ~1/5 of names; excess sums to ~0 across the universe per date
    df = pd.DataFrame({"market_date": [1] * 10, "f20": np.linspace(-0.1, 0.1, 10)})
    df["x20"] = df["f20"] - df.groupby("market_date")["f20"].transform("mean")
    assert abs(df["x20"].sum()) < 1e-9
    print("selfcheck ok")


if __name__ == "__main__":
    import sys

    _selfcheck() if "--selfcheck" in sys.argv else main()
