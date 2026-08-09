#!/usr/bin/env python3
"""Stage B — does swapping the RV leg for a GARCH forecast make argon's VRP a better signal?

Runs ONLY if Stage A (garch_vs_rv21_forecast.py) showed GARCH forecasts forward
realized vol better than the trailing RV21 argon uses today. Stage A is the
decisive test; this stage asks the narrower, weaker-powered question of whether
that forecast edge survives into the tradable signal.

    vrp_rv21 (today)  = iv - rv21_trailing
    vrp_garch (new)   = iv - garch_forecast_21d
    y (short-vol P&L) = iv - rv_forward_21d

Both signals share the SAME iv, so the iv term inflates the ABSOLUTE IC of both
identically (iv appears in signal and target). The DIFFERENCE in IC between the
two is therefore attributable purely to the RV leg — which is the only thing
being tested. Absolute IC numbers here are NOT tradable expectations; read the
delta, not the level.

POWER WARNING
    argon's IV panel starts 2025-05-12 and the price lake ends 2026-05-15, so the
    usable window is ~235 dates. Forward windows overlap 21 days => ~11 independent
    time blocks. This stage CANNOT produce a significant result on its own and is
    not expected to; it is a directional consistency check on Stage A.

SPX NOTE
    SPX has IV in argon but no price series in the lake (it is an index, not an
    ETF). --alias SPX=SPY pairs SPX's implied vol with SPY's realized/forecast
    vol. Legitimate: same underlying index, dividend-vs-total-return differences
    are noise at daily frequency. Matters because argon's WINNING macro structure
    is an SPX bull put spread, not an SPY one.

Reproduce:
    uv run python scripts/research/garch_vrp_signal_ic.py \
        --stage-a /tmp/stage_a.per_obs.parquet --alias SPX=SPY

Writes: <out-prefix>.per_obs.parquet  joined signal/target trace
        <out-prefix>.summary.json     machine-readable verdict
"""

from __future__ import annotations

import argparse
import json
import sys

import numpy as np
import pandas as pd
import psycopg

HORIZON = 21
RNG = np.random.default_rng(20260729)


def load_iv(dsn: str) -> pd.DataFrame:
    with psycopg.connect(dsn) as c:
        rows = c.execute(
            "select ticker, market_date, implied_volatility "
            "from uw_scan.realized_volatility_history "
            "where implied_volatility is not null"
        ).fetchall()
    df = pd.DataFrame(rows, columns=["ticker", "date", "iv"])
    df["date"] = pd.to_datetime(df["date"])
    df["iv"] = df["iv"].astype(float)
    return df


def add_z(df: pd.DataFrame, col: str, window: int) -> pd.Series:
    """Trailing z-score of `col` within each ticker — argon's vrp_z_20 convention."""
    g = df.groupby("ticker")[col]
    mu = g.transform(lambda s: s.rolling(window, min_periods=window).mean())
    sd = g.transform(lambda s: s.rolling(window, min_periods=window).std(ddof=1))
    return (df[col] - mu) / sd.replace(0.0, np.nan)


def cross_sectional_ic(df: pd.DataFrame, sig: str, tgt: str = "y") -> pd.Series:
    """Spearman IC computed WITHIN each date, so the common IV level cancels."""

    def _ic(g: pd.DataFrame) -> float:
        g = g[[sig, tgt]].dropna()
        if len(g) < 15 or g[sig].nunique() < 5:
            return np.nan
        return g[sig].corr(g[tgt], method="spearman")

    return df.groupby("date")[[sig, tgt]].apply(_ic).dropna()


def block_stats(ic: pd.Series, block: int = HORIZON) -> dict:
    """Mean IC with a block bootstrap CI — overlapping targets make a naive t-test lie."""
    ic = ic.sort_index()
    blocks = np.arange(len(ic)) // block
    per_block = pd.Series(ic.to_numpy()).groupby(blocks).mean().to_numpy()
    out = {
        "mean_ic": float(ic.mean()),
        "n_dates": int(len(ic)),
        "n_blocks": int(len(per_block)),
    }
    if len(per_block) >= 4:
        draws = RNG.choice(per_block, size=(5000, len(per_block)), replace=True).mean(1)
        out["ci_lo"] = float(np.percentile(draws, 2.5))
        out["ci_hi"] = float(np.percentile(draws, 97.5))
        out["p_le_zero"] = float((draws <= 0).mean())
    return out


def quintile_spread(df: pd.DataFrame, sig: str) -> dict:
    """Mean y of the top signal quintile minus the bottom, averaged over dates."""
    rows = []
    for d, g in df.groupby("date"):
        g = g[[sig, "y"]].dropna()
        if len(g) < 25:
            continue
        q = g[sig].rank(pct=True)
        rows.append(g.loc[q >= 0.8, "y"].mean() - g.loc[q <= 0.2, "y"].mean())
    if not rows:
        return {}
    a = np.array(rows)
    return {"mean_spread_vol_pts": float(a.mean() * 100), "n_dates": int(len(a))}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage-a", required=True, help="Stage A .per_obs.parquet")
    ap.add_argument("--dsn", default="dbname=option_wizard_local")
    ap.add_argument(
        "--alias",
        action="append",
        default=[],
        help="IV_TICKER=PRICE_TICKER, e.g. SPX=SPY (repeatable)",
    )
    ap.add_argument("--z-window", type=int, default=20, help="argon uses 20")
    ap.add_argument("--out-prefix", default="/tmp/garch_stage_b")
    args = ap.parse_args()

    vol = pd.read_parquet(args.stage_a)  # ticker,date,rv21,ewma,garch,rv_fwd
    iv = load_iv(args.dsn)

    # Alias IV tickers onto a price proxy (SPX -> SPY) before the join.
    amap = dict(a.split("=", 1) for a in args.alias)
    if amap:
        extra = iv[iv["ticker"].isin(amap)].copy()
        if not extra.empty:
            extra["price_ticker"] = extra["ticker"].map(amap)
            print(f"aliasing: {amap} ({len(extra)} IV rows)", file=sys.stderr)
        iv = pd.concat([iv.assign(price_ticker=iv["ticker"]), extra], ignore_index=True)
    else:
        iv["price_ticker"] = iv["ticker"]

    df = iv.merge(
        vol,
        left_on=["price_ticker", "date"],
        right_on=["ticker", "date"],
        how="inner",
        suffixes=("", "_px"),
    )
    if df.empty:
        print("empty join — check Stage A window vs IV window", file=sys.stderr)
        sys.exit(1)

    df["vrp_rv21"] = df["iv"] - df["rv21"]
    df["vrp_garch"] = df["iv"] - df["garch"]
    df["vrp_ewma"] = df["iv"] - df["ewma"]
    df["y"] = df["iv"] - df["rv_fwd"]

    df = df.sort_values(["ticker", "date"])
    for c in ("rv21", "garch", "ewma"):
        df[f"z_{c}"] = add_z(df, f"vrp_{c}", args.z_window)

    df.to_parquet(f"{args.out_prefix}.per_obs.parquet", index=False)

    summary: dict = {
        "n_obs": int(len(df)),
        "n_tickers": int(df["ticker"].nunique()),
        "date_range": [str(df["date"].min().date()), str(df["date"].max().date())],
        "z_window": args.z_window,
        "alias": amap,
        "mean_iv": float(df["iv"].mean()),
        "mean_rv_fwd": float(df["rv_fwd"].mean()),
        "mean_y_vol_pts": float(df["y"].mean() * 100),
    }
    for c in ("rv21", "garch", "ewma"):
        ic = cross_sectional_ic(df, f"z_{c}")
        summary[c] = {
            "xs_ic": block_stats(ic),
            "quintile": quintile_spread(df, f"z_{c}"),
            "mean_vrp_vol_pts": float(df[f"vrp_{c}"].mean() * 100),
        }

    # Paired per-date IC difference — the actual quantity of interest.
    ic_g = cross_sectional_ic(df, "z_garch")
    ic_r = cross_sectional_ic(df, "z_rv21")
    common = ic_g.index.intersection(ic_r.index)
    summary["ic_delta_garch_minus_rv21"] = block_stats(
        (ic_g.loc[common] - ic_r.loc[common])
    )

    with open(f"{args.out_prefix}.summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    print("=" * 64, file=sys.stderr)
    print(
        f"Stage B  n={summary['n_obs']:,}  {summary['n_tickers']} tickers  "
        f"{summary['date_range']}  z={args.z_window}",
        file=sys.stderr,
    )
    for c in ("rv21", "garch", "ewma"):
        s = summary[c]["xs_ic"]
        q = summary[c]["quintile"]
        print(
            f"  {c:6s} xsIC={s['mean_ic']:+.4f} "
            f"CI[{s.get('ci_lo', float('nan')):+.4f},{s.get('ci_hi', float('nan')):+.4f}] "
            f"blocks={s['n_blocks']}  Q5-Q1={q.get('mean_spread_vol_pts', float('nan')):+.2f}pts "
            f"meanVRP={summary[c]['mean_vrp_vol_pts']:+.2f}pts",
            file=sys.stderr,
        )
    d = summary["ic_delta_garch_minus_rv21"]
    print(
        f"  DELTA garch-rv21: {d['mean_ic']:+.4f} "
        f"CI[{d.get('ci_lo', float('nan')):+.4f},{d.get('ci_hi', float('nan')):+.4f}] "
        f"blocks={d['n_blocks']}",
        file=sys.stderr,
    )
    print(f"\n✓ {args.out_prefix}.summary.json", file=sys.stderr)


if __name__ == "__main__":
    main()
