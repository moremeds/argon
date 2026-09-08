#!/usr/bin/env python3
"""Track 2 — does a *richer* skew feature beat 25Δ RR at forward prediction?

Track 1 found the one surviving directional edge is single_name/NORMAL/CHASE
(momentum-confirmation, +3.6%/20d momentum-neutral), and that 25Δ RR *level* itself
carries ~no directional signal (it's a filter, not the driver). This asks whether a
different skew cut would carry more: recompute RR at 10Δ / 25Δ / 40Δ and an RR term-slope
from the full-chain IV grid (``option_surface_grid_daily``), then measure each feature's
cross-sectional rank-IC against the 20-day momentum-neutral forward return — over all
single names and the CHASE subset — on the ~6mo the grid covers (from 2025-12-26).

Sanity gate: grid-interpolated 25Δ RR must track the engine's banked ``rr_25d``. If it
does, the 10Δ/40Δ/slope ICs are trustworthy; if the winner is still ~0, the edge really is
momentum, not any skew cut.

Read-only. Reproduce:
    export PGPASSWORD=... UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard
    uv run --directory /Users/chenxi/projects/argon \
        python .worktrees/skew-directional-probe/scripts/oneshot/skew_richer_features.py
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg

HORIZON = 20
MOM_WINDOW = 63
FRONT_DTE, BACK_DTE = 30, 75
DELTAS = (0.10, 0.25, 0.40)
OUT = Path(__file__).resolve().parents[2] / "docs" / "research" / "skew-directional"


def _dsn() -> str:
    pw = os.environ.get("PGPASSWORD") or os.environ.get("UW_SCAN_DB_PASSWORD")
    if not pw:
        raise SystemExit("set PGPASSWORD — no secret is stored in this file")
    host = os.environ.get("UW_SCAN_DB_HOST", "100.66.147.98")
    name = os.environ.get("UW_SCAN_DB_NAME", "option_wizard")
    return f"host={host} port=5432 dbname={name} user=argon_app password={pw}"


def _rr_at(sub: pd.DataFrame, d: float) -> float:
    """put_iv(-d) - call_iv(+d) by delta-interpolation within one surface (no extrapolation)."""
    c = sub.dropna(subset=["call_delta", "call_iv"]).sort_values("call_delta")
    p = sub.dropna(subset=["put_delta", "put_iv"]).sort_values("put_delta")
    if len(c) < 2 or len(p) < 2:
        return np.nan
    if not (c.call_delta.min() <= d <= c.call_delta.max()):
        return np.nan
    if not (p.put_delta.min() <= -d <= p.put_delta.max()):
        return np.nan
    civ = np.interp(d, c.call_delta.to_numpy(), c.call_iv.to_numpy())
    piv = np.interp(-d, p.put_delta.to_numpy(), p.put_iv.to_numpy())
    return float(piv - civ)


def _surfaces() -> pd.DataFrame:
    with psycopg.connect(_dsn()) as conn:
        rows = conn.execute(
            """WITH sn AS (SELECT DISTINCT ticker FROM uw_scan.skew_analytics_snapshot
                          WHERE asset_class='single_name')
               SELECT g.ticker, g.market_date, g.expiry,
                      g.call_iv, g.put_iv, g.call_delta, g.put_delta
               FROM uw_scan.option_surface_grid_daily g JOIN sn USING (ticker)
               WHERE (g.expiry - g.market_date) BETWEEN 15 AND 130
                 AND (abs(g.call_delta) BETWEEN 0.05 AND 0.55
                      OR abs(g.put_delta) BETWEEN 0.05 AND 0.55)"""
        ).fetchall()
    df = pd.DataFrame(
        rows,
        columns=[
            "ticker",
            "market_date",
            "expiry",
            "call_iv",
            "put_iv",
            "call_delta",
            "put_delta",
        ],
    )
    for col in ["call_iv", "put_iv", "call_delta", "put_delta"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["dte"] = (
        pd.to_datetime(df["expiry"]) - pd.to_datetime(df["market_date"])
    ).dt.days
    return df


def _features(surf: pd.DataFrame) -> pd.DataFrame:
    """Per (ticker, date): RR@10/25/40 on the front (~30d) surface + term slope vs ~75d."""
    recs = []
    for (tkr, md), g in surf.groupby(["ticker", "market_date"]):
        exps = g.groupby("expiry")["dte"].first()
        front_exp = (exps - FRONT_DTE).abs().idxmin()
        back_exp = (exps - BACK_DTE).abs().idxmin()
        fsurf = g[g.expiry == front_exp]
        rr = {f"rr_{int(d * 100)}": _rr_at(fsurf, d) for d in DELTAS}
        slope = np.nan
        if back_exp != front_exp:
            slope = rr["rr_25"] - _rr_at(g[g.expiry == back_exp], 0.25)
        recs.append({"ticker": tkr, "market_date": md, **rr, "rr_slope": slope})
    return pd.DataFrame(recs)


def _fwd_and_class() -> pd.DataFrame:
    """Forward 20d momentum-neutral excess return + CHASE/deviation classification, single names."""
    with psycopg.connect(_dsn()) as conn:
        rvh = pd.DataFrame(
            conn.execute(
                "SELECT ticker, market_date, price FROM uw_scan.realized_volatility_history"
            ).fetchall(),
            columns=["ticker", "market_date", "price"],
        )
        snap = pd.DataFrame(
            conn.execute(
                """SELECT ticker, market_date, deviation_class, drive_class, rr_25d
               FROM uw_scan.skew_analytics_snapshot
               WHERE basis='eod' AND asset_class='single_name'"""
            ).fetchall(),
            columns=[
                "ticker",
                "market_date",
                "deviation_class",
                "drive_class",
                "rr_25d",
            ],
        )
    rvh["price"] = pd.to_numeric(rvh["price"], errors="coerce")
    rvh = rvh.dropna(subset=["price"]).sort_values(["ticker", "market_date"])
    rvh["fwd_ret"] = rvh.groupby("ticker")["price"].shift(-HORIZON) / rvh["price"] - 1.0
    rvh["mom"] = rvh["price"] / rvh.groupby("ticker")["price"].shift(MOM_WINDOW) - 1.0
    d = snap.merge(
        rvh[["ticker", "market_date", "fwd_ret", "mom"]],
        on=["ticker", "market_date"],
        how="inner",
    ).dropna(subset=["fwd_ret", "mom"])
    d["mom_decile"] = d.groupby("market_date")["mom"].transform(
        lambda s: (
            pd.qcut(s.rank(method="first"), 10, labels=False)
            if s.notna().sum() >= 10
            else -1
        )
    )
    d["exc_mom"] = d["fwd_ret"] - d.groupby(["market_date", "mom_decile"])[
        "fwd_ret"
    ].transform("mean")
    d["rr_25d"] = pd.to_numeric(d["rr_25d"], errors="coerce")
    return d


def _daily_ic(
    df: pd.DataFrame, feat: str, tgt: str = "exc_mom"
) -> tuple[float, float, int]:
    """Mean cross-sectional rank-IC over dates + t-stat of the daily IC series."""
    ics = []
    for _, g in df.dropna(subset=[feat, tgt]).groupby("market_date"):
        if g[feat].nunique() >= 5 and len(g) >= 5:
            ics.append(g[feat].rank().corr(g[tgt].rank()))
    ics = np.asarray([x for x in ics if pd.notna(x)], dtype=float)
    if ics.size < 3:
        return (float("nan"), float("nan"), ics.size)
    t = (
        ics.mean() / (ics.std(ddof=1) / np.sqrt(ics.size))
        if ics.std(ddof=1) > 0
        else float("nan")
    )
    return (float(ics.mean()), float(t), ics.size)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    feats = _features(_surfaces())
    fc = _fwd_and_class()
    m = feats.merge(fc, on=["ticker", "market_date"], how="inner")
    print(
        f"merged {len(m)} single-name ticker-days on the grid overlap "
        f"({m.market_date.min()} .. {m.market_date.max()})"
    )

    # sanity: grid-interpolated 25Δ RR vs engine's banked rr_25d
    s = m.dropna(subset=["rr_25", "rr_25d"])
    corr = s["rr_25"].corr(s["rr_25d"]) if len(s) > 10 else float("nan")
    print(
        f"\nSANITY grid rr_25 vs banked rr_25d: corr={corr:.3f}  (n={len(s)})  "
        f"grid_mean={s.rr_25.mean():.4f} banked_mean={s.rr_25d.mean():.4f}"
    )

    rows = []
    chase = m[m.drive_class == "CHASE"]
    for feat in ["rr_10", "rr_25", "rr_40", "rr_slope"]:
        ic_all, t_all, n_all = _daily_ic(m, feat)
        ic_ch, t_ch, n_ch = _daily_ic(chase, feat)
        rows.append(
            {
                "feature": feat,
                "IC_all": ic_all,
                "t_all": t_all,
                "days_all": n_all,
                "IC_chase": ic_ch,
                "t_chase": t_ch,
                "days_chase": n_ch,
            }
        )
    tbl = pd.DataFrame(rows)
    for c in ["IC_all", "t_all", "IC_chase", "t_chase"]:
        tbl[c] = tbl[c].round(4)
    print(
        "\nrank-IC vs 20d momentum-neutral forward return (single names, grid window):"
    )
    print(tbl.to_string(index=False))
    tbl.to_csv(OUT / "richer_feature_ic.csv", index=False)
    m.to_csv(OUT / "richer_features_panel.csv", index=False)
    print(f"\nwrote CSVs to {OUT}")


def _selfcheck() -> None:
    sub = pd.DataFrame(
        {
            "call_delta": [0.10, 0.25, 0.40, 0.55],
            "call_iv": [0.30, 0.28, 0.26, 0.25],
            "put_delta": [-0.55, -0.40, -0.25, -0.10],
            "put_iv": [0.34, 0.33, 0.32, 0.31],
        }
    )
    rr25 = _rr_at(sub, 0.25)
    assert abs(rr25 - (0.32 - 0.28)) < 1e-9, rr25  # put25 0.32 - call25 0.28 = 0.04
    assert np.isnan(_rr_at(sub, 0.90)), "must not extrapolate beyond observed deltas"
    print("selfcheck ok")


if __name__ == "__main__":
    import sys

    _selfcheck() if "--selfcheck" in sys.argv else main()
