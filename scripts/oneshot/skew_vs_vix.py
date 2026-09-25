#!/usr/bin/env python3
"""Does aggregate skew-fear carry information BEYOND VIX? (the decisive redundancy test)

The sentiment probe found aggregate skew-fear is a valid coincident thermometer
(net_fear vs trailing-20d SPY = -0.62, smooth autocorr 0.94) with a mild contrarian
tilt at extremes. But VIX is free, cleaner, and already a fear thermometer. If skew-fear
is just VIX rescaled, keep VIX and delete this. The distinct asset skew *could* offer:
single-name breadth (VIX is SPX-only) — cross-sectional fear VIX literally cannot see.

Three sub-questions, only the third decides it:
  A. redundancy  — corr(skew-fear, {VIX,VVIX,VIX3M}) in levels & changes. ~1.0 => it IS VIX.
  B. lead-lag    — cross-correlate Δnet_fear[t] vs ΔVIX[t+k]. peak at k<0 => skew leads.
  C. incremental — orthogonalize net_fear on VIX (residual = skew-SPECIFIC fear). Does the
                   residual (i) predict forward 20d SPY return beyond VIX, and (ii) predict
                   FUTURE VIX changes (fear VIX hasn't priced yet)? If residual ~ noise,
                   skew-fear adds nothing over VIX.

Overlap-honest: forward-return significance uses a non-overlapping (every-FWD) subsample,
not the ~95%-overlapping daily panel. Market proxy = SPY (fallback QQQ). Read-only.

Reproduce:
    export PGPASSWORD=... UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard
    uv run --directory /Users/chenxi/projects/argon \
        python .worktrees/skew-directional-probe/scripts/oneshot/skew_vs_vix.py
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg

FWD = 20
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
        vol = pd.DataFrame(
            conn.execute(
                """SELECT trade_date, symbol, close FROM uw_scan.vol_index_daily
                   WHERE symbol IN ('VIX','VVIX','VIX3M')"""
            ).fetchall(),
            columns=["market_date", "symbol", "close"],
        )
        mkt = pd.DataFrame(
            conn.execute(
                """SELECT ticker, market_date, price FROM uw_scan.realized_volatility_history
                   WHERE ticker IN ('SPY','QQQ')"""
            ).fetchall(),
            columns=["ticker", "market_date", "price"],
        )
    snap["rr_z"] = pd.to_numeric(snap["rr_z"], errors="coerce")
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

    vol["close"] = pd.to_numeric(vol["close"], errors="coerce")
    vw = vol.pivot(index="market_date", columns="symbol", values="close").reset_index()

    mkt["price"] = pd.to_numeric(mkt["price"], errors="coerce")
    proxy = "SPY" if (mkt.ticker == "SPY").any() else "QQQ"
    m = mkt[mkt.ticker == proxy].dropna(subset=["price"]).sort_values("market_date")
    m["r_fwd"] = m["price"].shift(-FWD) / m["price"] - 1.0

    df = agg.merge(vw, on="market_date", how="inner").merge(
        m[["market_date", "r_fwd"]], on="market_date", how="inner"
    )
    df = df.sort_values("market_date").reset_index(drop=True)
    # forward VIX change: does skew-fear anticipate VIX itself?
    df["vix_fwd_chg"] = df["VIX"].shift(-FWD) / df["VIX"] - 1.0
    df.attrs["proxy"] = proxy
    return df


def _corr(a: pd.Series, b: pd.Series) -> float:
    d = pd.concat([a, b], axis=1).dropna()
    return float(d.iloc[:, 0].corr(d.iloc[:, 1])) if len(d) >= 10 else float("nan")


def _ols(y: np.ndarray, X: np.ndarray) -> tuple[np.ndarray, float, np.ndarray]:
    """OLS with an explicit intercept already in X. Returns (beta, R2, residual)."""
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1.0 - float((resid**2).sum()) / ss_tot if ss_tot > 0 else float("nan")
    return beta, r2, resid


def _orthogonalize(target: pd.Series, on: pd.Series) -> pd.Series:
    """Residual of target after regressing on `on` (with intercept) — the part of target
    that VIX does NOT explain. Aligned on the shared non-null index."""
    d = pd.concat([target.rename("y"), on.rename("x")], axis=1).dropna()
    X = np.column_stack([np.ones(len(d)), d["x"].to_numpy()])
    _, _, resid = _ols(d["y"].to_numpy(), X)
    return pd.Series(resid, index=d.index)


def _nonoverlap_t(df: pd.DataFrame, feat: str, tgt: str) -> tuple[float, float, int]:
    """corr(feat, tgt) and its t-stat on an every-FWD non-overlapping subsample."""
    d = df.dropna(subset=[feat, tgt]).reset_index(drop=True)
    sub = d.iloc[::FWD]
    if len(sub) < 4:
        return (float("nan"), float("nan"), len(sub))
    r = float(sub[feat].corr(sub[tgt]))
    n = len(sub)
    t = r * np.sqrt((n - 2) / (1 - r**2)) if abs(r) < 1 else float("nan")
    return (r, t, n)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    df = _load()
    print(
        f"{len(df)} days {df.market_date.min()}..{df.market_date.max()}, "
        f"proxy={df.attrs['proxy']}, avg {df.n.mean():.0f} names/day"
    )
    df["d_fear"] = df["net_fear"].diff()
    df["d_rrz"] = df["mean_rrz"].diff()
    df["d_vix"] = df["VIX"].diff()

    print("\n=== A. redundancy — is skew-fear just VIX? (corr) ===")
    rows = []
    for sk in ["net_fear", "mean_rrz"]:
        for vx in ["VIX", "VVIX", "VIX3M"]:
            rows.append(
                {
                    "skew": sk,
                    "vol_index": vx,
                    "corr_level": round(_corr(df[sk], df[vx]), 3),
                    "corr_change": round(_corr(df[sk].diff(), df[vx].diff()), 3),
                }
            )
    a_tbl = pd.DataFrame(rows)
    print(a_tbl.to_string(index=False))
    a_tbl.to_csv(OUT / "vix_redundancy.csv", index=False)
    print("  (|corr_level| ~1 => skew-fear IS VIX; <~0.7 => meaningfully distinct)")

    print(
        "\n=== B. lead-lag — corr(Δnet_fear[t], ΔVIX[t+k]); k<0 => skew leads VIX ==="
    )
    lags = range(-10, 11, 2)
    ll = []
    for k in lags:
        ll.append(
            {"lag_k": k, "corr": round(_corr(df["d_fear"], df["d_vix"].shift(-k)), 3)}
        )
    ll_tbl = pd.DataFrame(ll)
    print(ll_tbl.to_string(index=False))
    ll_tbl.to_csv(OUT / "vix_leadlag.csv", index=False)
    peak = ll_tbl.iloc[ll_tbl["corr"].abs().idxmax()]
    print(
        f"  peak |corr| at k={int(peak['lag_k'])} ({peak['corr']:+.3f}); "
        "k=0 dominating => coincident, not leading"
    )

    print(
        "\n=== C. incremental — does the VIX-orthogonal skew residual carry signal? ==="
    )
    df["fear_resid"] = _orthogonalize(df["net_fear"], df["VIX"])
    # C.i forward SPY return: VIX alone vs VIX + net_fear (incremental R2)
    d = df.dropna(subset=["r_fwd", "VIX", "net_fear"])
    y = d["r_fwd"].to_numpy()
    X1 = np.column_stack([np.ones(len(d)), d["VIX"].to_numpy()])
    X2 = np.column_stack(
        [np.ones(len(d)), d["VIX"].to_numpy(), d["net_fear"].to_numpy()]
    )
    _, r2_vix, _ = _ols(y, X1)
    _, r2_both, _ = _ols(y, X2)
    print(
        f"  forward-{FWD}d {df.attrs['proxy']} return R^2:  VIX-only={r2_vix:.4f}  "
        f"VIX+net_fear={r2_both:.4f}  (incremental {r2_both - r2_vix:+.4f})"
    )
    r_res, t_res, n_res = _nonoverlap_t(df, "fear_resid", "r_fwd")
    r_vix, t_vix, _ = _nonoverlap_t(df, "VIX", "r_fwd")
    print(
        f"  non-overlapping (n={n_res}) corr vs forward return:  "
        f"VIX={r_vix:+.3f} (t={t_vix:.2f})   skew_resid={r_res:+.3f} (t={t_res:.2f})"
    )
    # C.ii does skew_resid anticipate FUTURE VIX moves VIX itself hasn't shown?
    r_antic, t_antic, n_antic = _nonoverlap_t(df, "fear_resid", "vix_fwd_chg")
    print(
        f"  skew_resid vs FUTURE {FWD}d VIX change: corr={r_antic:+.3f} "
        f"(t={t_antic:.2f}, n={n_antic})  >0 => fear leads a VIX rise VIX hasn't priced"
    )

    print(
        "\n=== C.iii breadth extremes controlling for VIX (quintiles of skew_resid) ==="
    )
    dd = df.dropna(subset=["fear_resid", "r_fwd", "VIX"]).copy()
    dd["resid_q"] = pd.qcut(dd["fear_resid"].rank(method="first"), 5, labels=False)
    ext = (
        dd.groupby("resid_q")
        .agg(
            days=("r_fwd", "size"),
            fear_resid=("fear_resid", "mean"),
            avg_VIX=("VIX", "mean"),
            fwd20=("r_fwd", "mean"),
        )
        .round(4)
    )
    print(ext.to_string())
    print(
        "  (if avg_VIX is flat across resid quintiles but fwd20 still sorts, the signal is\n"
        "   VIX-orthogonal breadth; if fwd20 is flat, skew adds nothing beyond VIX)"
    )
    df.to_csv(OUT / "vix_series.csv", index=False)
    print(f"\nwrote CSVs to {OUT}")


def _selfcheck() -> None:
    # _ols: noiseless y=2x+1 -> beta=[1,2], R2=1, resid=0
    x = np.arange(1.0, 21.0)
    X = np.column_stack([np.ones_like(x), x])
    beta, r2, resid = _ols(2 * x + 1, X)
    assert abs(beta[0] - 1) < 1e-9 and abs(beta[1] - 2) < 1e-9, beta
    assert abs(r2 - 1.0) < 1e-9 and np.allclose(resid, 0, atol=1e-9), (r2, resid)
    # _orthogonalize: residual must be ~uncorrelated with the regressor it was removed on
    t = pd.Series(x + np.array([0, 1, -1, 2, -2] * 4, float))  # x plus zero-mean wiggle
    res = _orthogonalize(t, pd.Series(x))
    assert abs(float(pd.Series(res.to_numpy()).corr(pd.Series(x)))) < 1e-6, "resid ⟂ x"
    print("selfcheck ok")


if __name__ == "__main__":
    import sys

    _selfcheck() if "--selfcheck" in sys.argv else main()
