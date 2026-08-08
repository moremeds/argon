#!/usr/bin/env python3
"""E1 — calibrate the ATM-IV cone against realised moves (spec §3.2).

Reproduce (reads the mini's prodlike DB read-only; password from the
UW_SCAN_DB_PASSWORD env var or the repo .env, never a CLI argument):

    uv run python scripts/research/magnet_cone_calibration.py \
        --host 100.66.147.98 --dbname option_wizard --user argon_app \
        --out docs/research/2026-08-08-magnet-cone-calibration

POWER WARNING
    The option surface spans 2025-12-26 -> 2026-08-07, about 154 trading
    sessions. At h=5 that is ~149 overlapping observations per ticker but only
    ~29 independent ones; at h=10, ~14. The 21d horizon is NOT run — see spec
    §3.3. Pooling ~150 tickers does not multiply power by 150: they share a
    volatility factor and the watchlist is concentrated in AI/semis, so the
    effective sample is materially below nominal. Read the bootstrap CIs, not
    the point estimates.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg
from scipy.stats import kstest

from uw_scan.backtest.splitters import time_ordered_holdout
from uw_scan.reports.magnet_calibration import (
    NOMINAL_COVERAGE,
    coverage,
    nonoverlapping_subsample,
    panel_block_bootstrap,
    pit,
    scale_estimates,
)
from uw_scan.reports.magnet_data import (
    atm_iv_at_horizon,
    load_adjusted_closes,
    load_all_expiry_iv_curves,
    load_all_session_spots,
)

HORIZONS = (5, 10)  # 21 withheld: ~14 independent windows, no power
MIN_OBS = 100  # spec §3.2 — below this, k is noise carrying full weight
TRADING_DAYS = 252
CAL_PER_TRADING_DAY = 7 / 5  # trading-day horizon -> calendar DTE target


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def resolve_password() -> str | None:
    """Password from env, falling back to the repo dotenv. Never a CLI arg and
    never echoed — it would land in shell history and in this script's own log."""
    for key in ("UW_SCAN_DB_PASSWORD", "PGPASSWORD"):
        if os.environ.get(key):
            return os.environ[key]
    try:
        from dotenv import dotenv_values

        merged = {**dotenv_values(".env"), **dotenv_values(".env.local")}
        return merged.get("UW_SCAN_DB_PASSWORD")
    except Exception:
        return None


def grid_tickers(conn, schema: str) -> list[str]:
    sql = f"SELECT DISTINCT ticker FROM {schema}.option_surface_grid_daily ORDER BY ticker"
    return [r[0] for r in conn.execute(sql).fetchall()]


def observations(conn, ticker: str, schema: str) -> list[dict]:
    """One row per (session, horizon) with a usable IV and a forward close.

    THREE round trips per ticker, not three per ticker-session. Over a 141 ms
    Tailscale link the per-session shape was ~46k round trips (~90 min of pure
    latency) and was abandoned mid-run for exactly that reason.
    """
    px = load_adjusted_closes(conn, ticker, schema)
    if px.empty:
        return []
    px = px.reset_index(drop=True)
    close = px["close"].to_numpy(dtype=float)
    idx_of = {d: i for i, d in enumerate(px["date"])}

    spots = load_all_session_spots(conn, ticker, schema)
    if not spots:
        return []
    curves = load_all_expiry_iv_curves(conn, ticker, spots, schema)

    out: list[dict] = []
    for as_of in sorted(spots):
        i = idx_of.get(as_of)
        if i is None:
            continue
        curve = curves.get(as_of)
        if not curve:
            continue
        for h in HORIZONS:
            j = i + h
            if j >= len(close):
                continue
            target_dte = max(1, round(h * CAL_PER_TRADING_DAY))
            sigma = atm_iv_at_horizon(curve, target_dte)
            if sigma is None or sigma <= 0:
                continue
            # Returns from the BACK-ADJUSTED series on both endpoints.
            log_ret = float(np.log(close[j] / close[i]))
            t = h / TRADING_DAYS
            z = (log_ret + 0.5 * sigma**2 * t) / (sigma * np.sqrt(t))
            out.append(
                {
                    "ticker": ticker,
                    "as_of": as_of,
                    "horizon": h,
                    "sigma": sigma,
                    "log_ret": log_ret,
                    "z": float(z),
                }
            )
    return out


def summarise(sub: pd.DataFrame, horizon: int, label: str) -> dict:
    """One row of calibration diagnostics.

    Uses panel_block_bootstrap for EVERY scope, pooled and per-ticker alike.
    For a single ticker the panel version degenerates exactly to the
    moving-block version — one observation per date means resampling blocks of
    dates IS resampling blocks of the series — so a pooled-vs-per-ticker switch
    buys nothing and costs a decision that, made wrongly, silently narrows the
    CI ~6x and flips G3.
    """
    z = sub["z"].to_numpy(dtype=float)
    est = scale_estimates(z)
    row = {"scope": label, "horizon": horizon, **est}
    for level, nominal in NOMINAL_COVERAGE.items():
        row[f"cov_{level}"] = coverage(z, level)
        row[f"cov_{level}_nominal"] = nominal

    # PIT + KS (spec §3.2) on a NON-OVERLAPPING subsample only: at h=5
    # consecutive rows share 4 of 5 days and a KS p-value on overlapping data is
    # not merely imprecise, it is meaningless.
    u_indep = pit(nonoverlapping_subsample(z, step=horizon))
    if u_indep.size >= 20:
        ks = kstest(u_indep, "uniform")
        row["pit_ks_stat"] = float(ks.statistic)
        row["pit_ks_p"] = float(ks.pvalue)
    else:
        row["pit_ks_stat"] = row["pit_ks_p"] = float("nan")
    row["pit_ks_n_indep"] = int(u_indep.size)

    if z.size >= max(MIN_OBS, horizon * 2):

        def k_stat(a: np.ndarray) -> float:
            return float(np.std(a, ddof=1))

        boot = panel_block_bootstrap(
            sub["as_of"].to_numpy(),
            z,
            k_stat,
            block=horizon,
            n_boot=1000,
            seed=20260808,
        )
        row["k_ci_lo"], row["k_ci_hi"] = boot["lo"], boot["hi"]
        row["ci_n_dates"] = boot.get("n_dates")
    else:
        row["k_ci_lo"] = row["k_ci_hi"] = float("nan")
    return row


def oos_calibration(sub: pd.DataFrame, holdout_frac: float = 0.4) -> dict:
    """G2 — fit k on the front window, validate coverage on the held-out tail.

    An in-sample k trivially reproduces nominal coverage in-sample; that is not
    evidence of anything. The gate is whether shrinking by a k the tail never saw
    lands the tail's coverage closer to nominal.
    """
    rows = sub.sort_values("as_of").to_dict("records")
    if len(rows) < 2 * MIN_OBS:
        return {"status": "insufficient", "n": len(rows)}
    ordered, holdout = time_ordered_holdout(
        rows, key=lambda r: r["as_of"], frac=holdout_frac
    )
    train = ordered[: len(ordered) - len(holdout)]
    if len(train) < MIN_OBS or len(holdout) < MIN_OBS:
        return {"status": "insufficient", "n_train": len(train), "n_test": len(holdout)}

    k_train = scale_estimates(np.array([r["z"] for r in train]))["std"]
    if not np.isfinite(k_train) or k_train <= 0:
        return {"status": "bad_k", "k_train": k_train}

    z_test = np.array([r["z"] for r in holdout])
    out = {
        "status": "ok",
        "k_train": float(k_train),
        "n_train": len(train),
        "n_test": len(holdout),
        "train_end": str(train[-1]["as_of"]),
    }
    for level, nominal in NOMINAL_COVERAGE.items():
        raw = coverage(z_test, level)
        cal = coverage(z_test / k_train, level)
        out[f"oos_cov_{level}_raw"] = raw
        out[f"oos_cov_{level}_calibrated"] = cal
        out[f"oos_cov_{level}_nominal"] = nominal
        # Calibration must move coverage TOWARD nominal, not merely change it.
        out[f"oos_cov_{level}_improved"] = bool(abs(cal - nominal) < abs(raw - nominal))
    out["g2_pass"] = bool(out["oos_cov_1.0_improved"] and out["oos_cov_1.96_improved"])
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="100.66.147.98")
    ap.add_argument("--dbname", default="option_wizard")
    ap.add_argument("--user", default="argon_app")
    ap.add_argument("--schema", default="uw_scan")
    ap.add_argument("--out", default="docs/research/2026-08-08-magnet-cone-calibration")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    with psycopg.connect(
        host=args.host,
        dbname=args.dbname,
        user=args.user,
        password=resolve_password(),
        connect_timeout=20,
    ) as conn:
        tickers = grid_tickers(conn, args.schema)
        print(f"tickers in grid: {len(tickers)}")
        for n, t in enumerate(tickers, 1):
            rows.extend(observations(conn, t, args.schema))
            if n % 25 == 0:
                print(f"  {n}/{len(tickers)} tickers, {len(rows)} obs")

    if not rows:
        raise SystemExit("no observations — check connection and grid coverage")

    per_obs = pd.DataFrame(rows)
    per_obs["u_pit"] = pit(per_obs["z"].to_numpy(dtype=float))
    per_obs.to_csv(out_dir / "per_obs.csv", index=False)

    summaries: list[dict] = []
    for h in HORIZONS:
        sub = per_obs[per_obs["horizon"] == h]
        if sub.empty:
            continue
        summaries.append(summarise(sub, h, "pooled"))
        for tkr, grp in sub.groupby("ticker"):
            if len(grp) < MIN_OBS:
                continue
            summaries.append(summarise(grp, h, f"ticker:{tkr}"))

    by_ticker = pd.DataFrame(summaries)
    by_ticker.to_csv(out_dir / "by_ticker.csv", index=False)

    excluded = sorted(
        {
            f"{t}@{h}"
            for h in HORIZONS
            for t, g in per_obs[per_obs["horizon"] == h].groupby("ticker")
            if len(g) < MIN_OBS
        }
    )

    # G2: does a k the holdout never saw pull the holdout's coverage to nominal?
    g2 = {str(h): oos_calibration(per_obs[per_obs["horizon"] == h]) for h in HORIZONS}

    # G3: does per-ticker k dispersion exceed the pooled PANEL-bootstrap CI width?
    g3: dict = {}
    for h in HORIZONS:
        per_t = by_ticker[
            (by_ticker["horizon"] == h) & (by_ticker["scope"].str.startswith("ticker:"))
        ]
        pooled = by_ticker[
            (by_ticker["horizon"] == h) & (by_ticker["scope"] == "pooled")
        ]
        if per_t.empty or pooled.empty or len(per_t) < 2:
            g3[str(h)] = {"status": "insufficient", "n_tickers": int(len(per_t))}
            continue
        ci_width = float(pooled["k_ci_hi"].iloc[0] - pooled["k_ci_lo"].iloc[0])
        dispersion = float(per_t["std"].std(ddof=1))
        g3[str(h)] = {
            "n_tickers": int(len(per_t)),
            "per_ticker_k_std": dispersion,
            "pooled_k_ci_width": ci_width,
            "pooled_k": float(pooled["std"].iloc[0]),
            "per_ticker_table_justified": bool(dispersion > ci_width),
        }

    summary = {
        "spec": "docs/superpowers/specs/2026-08-08-technicals-magnet-view-design.md",
        "git_sha": git_sha(),
        "source_db": f"{args.host}/{args.dbname}",
        "reproduce_cmd": (
            "uv run python scripts/research/magnet_cone_calibration.py "
            f"--host {args.host} --dbname {args.dbname} --user {args.user} "
            f"--out {args.out}"
        ),
        "generated_for_date": str(date.today()),
        "horizons": list(HORIZONS),
        "horizons_withheld": {"21": "~14 independent windows per ticker — no power"},
        "min_obs": MIN_OBS,
        "n_excluded_ticker_horizons": len(excluded),
        "excluded_ticker_horizons": excluded,
        "n_obs": int(len(per_obs)),
        "n_tickers": int(per_obs["ticker"].nunique()),
        "date_range": [str(per_obs["as_of"].min()), str(per_obs["as_of"].max())],
        "g2_oos_calibration": g2,
        "g3_per_ticker_dispersion": g3,
        "note": (
            "mean(z) is an equity-risk-premium diagnostic and is NEVER applied. "
            "CIs are panel block bootstrap (resample dates, keep every ticker); "
            "no closed-form p-value is valid here. KS runs on non-overlapping "
            "subsamples only. Per-SECTOR pooling from spec 3.2 is omitted: no "
            "verified sector column exists and inventing one would be fabrication."
        ),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    print(
        json.dumps(
            {k: v for k, v in summary.items() if k != "excluded_ticker_horizons"},
            indent=2,
            default=str,
        )
    )


if __name__ == "__main__":
    main()
