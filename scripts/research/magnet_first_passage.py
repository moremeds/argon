#!/usr/bin/env python3
"""E2 — does R + 0.618*leg get touched before S? (spec §3.4)

Sweeps the ATR-zigzag threshold and scores each setting against a block-bootstrap
null built from each ticker's own returns up to the entry bar.

Reproduce (reads the mini read-only; sweep rows are written to the LOCAL dev DB
because option_wizard is writer-owned by the mini stack — see the three-tier
isolation policy in CLAUDE.md):

    uv run python scripts/research/magnet_first_passage.py \
        --host 100.66.147.98 --dbname option_wizard --user argon_app \
        --sweep-dsn "dbname=option_wizard_local" \
        --out docs/research/2026-08-08-magnet-cone-calibration

GATE G1
    Requires the LOWER BOUND of a ticker-clustered bootstrap CI to clear zero at
    a Bonferroni-adjusted level, not a point estimate. Testing "is the best of
    five configs > 0" passes 70-97% of the time when the true edge is exactly
    zero. G1 failing does NOT cancel the view — only the measured-move framing.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import zlib
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg
from magnet_cone_calibration import resolve_password  # noqa: E402

from uw_scan.backtest.splitters import time_ordered_holdout
from uw_scan.backtest.sweep import run_sweep
from uw_scan.cards.magnets import all_pivots
from uw_scan.reports.magnet_data import load_adjusted_closes
from uw_scan.reports.magnet_passage import (
    bootstrap_null_hit_rate,
    clustered_bootstrap_edge,
    first_passage,
    measured_move,
)
from uw_scan.storage.backtest_repository import BacktestRepository

K_GRID = (2.0, 2.5, 3.0, 3.5, 4.0)
MAX_BARS = 60
HOLDOUT_FRAC = 0.4
N_NULL_PATHS = 400
NULL_BLOCK = 5
MIN_BARS = 200


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def rising_legs(df: pd.DataFrame, k: float) -> list[dict]:
    """One row per rising leg — the state the reference calls ON THE WAY UP.

    A leg is (top pivot A, bottom pivot B) with B the LATER of the two and
    R > S. Price is measured forward from B's CONFIRMATION bar.
    """
    pivots = all_pivots(df, k=k)
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    out: list[dict] = []
    for a, b in zip(pivots, pivots[1:]):
        if not (a.kind == "top" and b.kind == "bottom"):
            continue
        if a.price <= b.price:
            continue
        stretch, down_level = measured_move(a.price, b.price)
        # LOOKAHEAD GUARD. Entry is the bar after the pivot is CONFIRMED, not the
        # bar after the pivot itself. b.index is the low; b.confirmed_index is the
        # first bar anyone could have known it was a low — measured 3-25 bars and
        # 8-14% of price later.
        #
        # Using b.index + 1 does NOT flatter the result, it wrecks it: entry then
        # sits on top of the support barrier (down = b.price), so nearly any
        # downtick stops out immediately — 65.7% stop rate vs 42.4%, and a hit
        # rate 16.6pt LOWER, measured on 1517 driftless-GBM legs.
        entry = b.confirmed_index + 1
        if entry >= len(df):
            continue
        out.append(
            {
                "entry_index": entry,
                "entry_date": df["date"].iloc[entry],
                "entry_price": float(close[entry]),
                "pivot_index": b.index,
                "confirm_lag_bars": b.confirmed_index - b.index,
                "resistance": a.price,
                "support": b.price,
                "stretch": stretch,
                "down": down_level,
                "outcome": first_passage(
                    high[entry:],
                    low[entry:],
                    up=stretch,
                    down=b.price,
                    max_bars=MAX_BARS,
                ),
            }
        )
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="100.66.147.98")
    ap.add_argument("--dbname", default="option_wizard")
    ap.add_argument("--user", default="argon_app")
    ap.add_argument("--sweep-dsn", default="dbname=option_wizard_local")
    ap.add_argument("--schema", default="uw_scan")
    ap.add_argument("--out", default="docs/research/2026-08-08-magnet-cone-calibration")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    # READ leg: the mini's prodlike DB, read-only.
    with psycopg.connect(
        host=args.host,
        dbname=args.dbname,
        user=args.user,
        password=resolve_password(),
        connect_timeout=20,
    ) as read_conn:
        tickers = [
            r[0]
            for r in read_conn.execute(
                f"SELECT DISTINCT ticker FROM {args.schema}.option_surface_grid_daily "
                "ORDER BY ticker"
            ).fetchall()
        ]
        prices: dict[str, pd.DataFrame] = {}
        for t in tickers:
            df = load_adjusted_closes(read_conn, t, args.schema)
            if len(df) >= MIN_BARS:
                prices[t] = df
    print(f"tickers with >={MIN_BARS} bars: {len(prices)} of {len(tickers)}")

    all_rows: list[dict] = []

    def run_one(config: dict) -> dict:
        k = config["k_atr"]
        legs: list[dict] = []
        for t, df in prices.items():
            tl = rising_legs(df, k)
            for row in tl:
                row["ticker"] = t
                row["k_atr"] = k
            closes = df["close"].to_numpy(dtype=float)
            for row in tl:
                entry = row["entry_index"]
                # SECOND LOOKAHEAD GUARD. The null resamples the ticker's own
                # returns, so it must only see returns available AT ENTRY.
                past = np.diff(np.log(closes[: entry + 1]))
                if past.size < NULL_BLOCK:
                    row["null_hit"] = float("nan")
                    continue
                null = bootstrap_null_hit_rate(
                    past,
                    row["entry_price"],
                    up=row["stretch"],
                    down=row["support"],
                    max_bars=MAX_BARS,
                    block=NULL_BLOCK,
                    n_paths=N_NULL_PATHS,
                    # Per-leg seed. One shared seed draws the SAME block-start
                    # sequence for every leg, so the null errors are perfectly
                    # correlated and averaging removes far less noise than the
                    # leg count suggests. crc32 not hash(): Python string hashing
                    # is randomised per process, which would make the run
                    # unreproducible while looking deterministic in any session.
                    seed=20260808 + zlib.crc32(f"{t}:{entry}".encode()),
                )
                row["null_hit"] = null["hit"]
            legs.extend(tl)
        all_rows.extend(legs)

        if not legs:
            return {
                "metrics": {"n_legs": 0},
                "gates": {"g1_beats_null": False},
                "n_trades": 0,
            }

        _, holdout = time_ordered_holdout(
            legs, key=lambda r: r["entry_date"], frac=HOLDOUT_FRAC
        )

        def share(rows: list[dict], kind: str) -> float:
            return (
                sum(1 for r in rows if r["outcome"] == kind) / len(rows)
                if rows
                else float("nan")
            )

        def hit_ex_ambiguous(rows: list[dict]) -> float:
            """Hit rate with same-bar double-touches removed. The null runs on
            synthetic closes with no intrabar range and can never return
            'ambiguous', so leaving it in the observed denominator would
            understate the edge by exactly the ambiguous share."""
            decided = [r for r in rows if r["outcome"] != "ambiguous"]
            if not decided:
                return float("nan")
            return sum(1 for r in decided if r["outcome"] == "hit") / len(decided)

        # G1 MULTIPLICITY: the sweep tries len(K_GRID) thresholds and reports the
        # best, so the level is Bonferroni-adjusted and the gate reads the CI
        # lower bound, never the point estimate.
        alpha = 0.05 / len(K_GRID)
        ci_all = clustered_bootstrap_edge(legs, n_boot=2000, seed=20260808, alpha=alpha)
        ci_oos = clustered_bootstrap_edge(
            holdout, n_boot=2000, seed=20260808, alpha=alpha
        )

        metrics = {
            "n_legs": len(legs),
            "hit": share(legs, "hit"),
            "stop": share(legs, "stop"),
            "ambiguous": share(legs, "ambiguous"),
            "neither": share(legs, "neither"),
            "hit_ex_ambiguous": hit_ex_ambiguous(legs),
            "median_confirm_lag_bars": float(
                np.median([r["confirm_lag_bars"] for r in legs])
            ),
            "null_hit_mean": float(
                np.nanmean([r.get("null_hit", np.nan) for r in legs])
            ),
            "edge_vs_null": ci_all["point"],
            "edge_ci_lo": ci_all["lo"],
            "edge_ci_hi": ci_all["hi"],
            "oos_n_legs": len(holdout),
            "oos_hit_ex_ambiguous": hit_ex_ambiguous(holdout),
            "oos_edge_vs_null": ci_oos["point"],
            "oos_edge_ci_lo": ci_oos["lo"],
            "oos_edge_ci_hi": ci_oos["hi"],
            "oos_edge_n_clusters": ci_oos["n_clusters"],
            "alpha_adjusted": alpha,
        }
        lo = ci_oos["lo"]
        gates = {
            # NaN != NaN, so this also rejects an unmeasurable edge.
            "g1_beats_null": bool(lo == lo and lo > 0.0),
            "g1_oos_legs_sufficient": bool(ci_oos["n"] >= 30),
            "g1_enough_clusters": bool(ci_oos["n_clusters"] >= 10),
        }
        return {"metrics": metrics, "gates": gates, "n_trades": len(legs)}

    # WRITE leg: the local dev DB. option_wizard on the mini is writer-owned by
    # the mini stack; writing sweep rows there from a laptop violates the
    # three-tier isolation policy even though the read above is legitimate.
    with psycopg.connect(args.sweep_dsn) as write_conn:
        repo = BacktestRepository(write_conn, schema=args.schema)
        result = run_sweep(
            [{"k_atr": k} for k in K_GRID],
            run_one,
            repo=repo,
            strategy="magnet_first_passage",
            reproduce_cmd=(
                "uv run python scripts/research/magnet_first_passage.py "
                f"--host {args.host} --dbname {args.dbname} --user {args.user} "
                f"--sweep-dsn '{args.sweep_dsn}' --out {args.out}"
            ),
            params_grid={
                "k_atr": list(K_GRID),
                "max_bars": MAX_BARS,
                "holdout_frac": HOLDOUT_FRAC,
                "n_null_paths": N_NULL_PATHS,
                "null_block": NULL_BLOCK,
                "min_bars": MIN_BARS,
            },
            git_sha=git_sha(),
            notes=(
                f"E2 spec 2026-08-08 3.4. Read {args.host}/{args.dbname}. Null is a "
                "block bootstrap of each ticker's own PRE-ENTRY returns; entries at "
                "confirmed_index+1; 'ambiguous' (both barriers in one bar) is NOT "
                "folded into hit or stop. G1 reads the clustered CI lower bound at "
                "Bonferroni alpha, not the point estimate."
            ),
        )

    if all_rows:
        pd.DataFrame(all_rows).to_csv(out_dir / "first_passage_legs.csv", index=False)

    payload = {
        "run_id": result["run_id"],
        "n_ok": result["n_ok"],
        "n_error": result["n_error"],
        "sweep_db": args.sweep_dsn,
        "read_db": f"{args.host}/{args.dbname}",
        "n_tickers": len(prices),
        "configs": [
            {"config": r["config"], "metrics": r["metrics"], "gates": r["gates"]}
            for r in result["results"]
        ],
    }
    (out_dir / "first_passage_summary.json").write_text(
        json.dumps(payload, indent=2, default=str)
    )
    print(json.dumps(payload, indent=2, default=str))


if __name__ == "__main__":
    main()
