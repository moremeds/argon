#!/usr/bin/env python3
"""Backtest CRI across the full available history.

Reads:
  - vol_index_daily for VIX, VVIX, COR1M
  - daily_ohlc for SPY

Recomputes CRI for every aligned trading day. The aligned window is bounded
by the *shortest* series in the warm store — usually SPY daily_ohlc.
For a longer (20y) walk-forward validation against the parquet data lake,
see docs/research/regime/cri-validation.ipynb.

Writes:
  - docs/research/regime/cri-backtest.csv (one row per day)
  - docs/research/regime/cri-backtest.md  (summary report)

Usage:
  uv run python scripts/backtest_cri.py
  uv run python scripts/backtest_cri.py --start 2006-01-01 --end 2026-05-15
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from collections import Counter
from datetime import date as _date
from pathlib import Path
from typing import Any

import numpy as np
import psycopg

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from uw_scan.cards import cri_scoring  # noqa: E402
from uw_scan.config import Settings  # noqa: E402

log = logging.getLogger("backtest_cri")

NAMED_CRASH_DATES = {
    "2008-09-15": "Lehman bankruptcy",
    "2008-10-10": "GFC bottom area",
    "2010-05-06": "Flash crash",
    "2011-08-08": "US credit downgrade",
    "2015-08-24": "Black Monday (China)",
    "2018-02-05": "Volmageddon",
    "2018-12-24": "Q4 selloff trough",
    "2020-02-28": "COVID early break",
    "2020-03-16": "COVID circuit breaker",
    "2022-06-13": "Rate-hike vol",
    "2024-08-05": "Yen-carry unwind",
}


def fetch_aligned_series(
    conn: psycopg.Connection, schema: str, start: _date, end: _date
) -> tuple[dict[str, np.ndarray], list[str]]:
    """Fetch and align all four series on shared dates."""
    series: dict[str, dict[_date, float]] = {}
    with conn.cursor() as cur:
        for sym in ("VIX", "VVIX", "COR1M"):
            cur.execute(
                f"SELECT trade_date, close FROM {schema}.vol_index_daily "
                "WHERE symbol = %s AND trade_date BETWEEN %s AND %s "
                "AND close IS NOT NULL ORDER BY trade_date",
                (sym, start, end),
            )
            series[sym] = {r[0]: float(r[1]) for r in cur.fetchall()}

        # Prefer SPX (CBOE-aligned, longer history) — fall back to SPY
        cur.execute(
            f"SELECT trade_date, close FROM {schema}.vol_index_daily "
            "WHERE symbol = 'SPX' AND trade_date BETWEEN %s AND %s "
            "AND close IS NOT NULL ORDER BY trade_date",
            (start, end),
        )
        spx = {r[0]: float(r[1]) for r in cur.fetchall()}
        if spx:
            series["SPY"] = spx  # downstream key stays "SPY" for back-compat
        else:
            cur.execute(
                f"SELECT date, close FROM {schema}.daily_ohlc "
                "WHERE ticker = 'SPY' AND date BETWEEN %s AND %s "
                "AND close IS NOT NULL ORDER BY date",
                (start, end),
            )
            series["SPY"] = {r[0]: float(r[1]) for r in cur.fetchall()}

    common = set(series["VIX"].keys())
    for sym in ("VVIX", "COR1M", "SPY"):
        common &= set(series[sym].keys())
    sorted_dates = sorted(common)
    aligned = {
        sym: np.array([series[sym][d] for d in sorted_dates], dtype=float)
        for sym in series
    }
    return aligned, [d.isoformat() for d in sorted_dates]


def compute_cri_for_window(
    aligned: dict[str, np.ndarray], common_dates: list[str]
) -> dict[str, Any]:
    """Pure passthrough to cri_scoring.run_analysis (kept here for testability)."""
    return cri_scoring.run_analysis(aligned, common_dates)


def rolling_compute(
    aligned: dict[str, np.ndarray],
    common_dates: list[str],
    window: int = 150,
) -> list[dict[str, Any]]:
    """Slide a `window`-day lookback over the full history, computing CRI per day.

    Returns a list of {date, score, level, vix_c, vvix_c, corr_c, trend_c, fired}.
    """
    out: list[dict[str, Any]] = []
    n = len(common_dates)
    for i in range(window, n):
        win_aligned = {sym: arr[i - window : i + 1] for sym, arr in aligned.items()}
        win_dates = common_dates[i - window : i + 1]
        try:
            p = cri_scoring.run_analysis(win_aligned, win_dates)
        except Exception as exc:  # pragma: no cover — defensive
            log.warning("backtest day %s skipped: %s", common_dates[i], repr(exc))
            continue
        cri = p["cri"]
        out.append(
            {
                "date": common_dates[i],
                "score": cri["score"],
                "level": cri["level"],
                "vix_c": cri["components"]["vix"],
                "vvix_c": cri["components"]["vvix"],
                "corr_c": cri["components"]["correlation"],
                "trend_c": cri["components"]["momentum"],
                "fired": p["crash_trigger"]["fired"],
                "vix": p["vix"],
                "vvix": p["vvix"],
                "cor1m": p["cor1m"],
                "spx_distance_pct": p["spx_distance_pct"],
            }
        )
    return out


def summarize_distribution(scores: list[float]) -> dict[str, Any]:
    arr = np.array(scores, dtype=float)
    return {
        "n": int(arr.size),
        "mean": float(arr.mean()),
        "min": float(arr.min()),
        "max": float(arr.max()),
        "p25": float(np.percentile(arr, 25)),
        "p50": float(np.percentile(arr, 50)),
        "p75": float(np.percentile(arr, 75)),
        "p90": float(np.percentile(arr, 90)),
        "p95": float(np.percentile(arr, 95)),
        "p99": float(np.percentile(arr, 99)),
        "level_counts": dict(Counter([cri_scoring.cri_level(s) for s in scores])),
    }


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        for r in rows:
            w.writerow(r)
    log.info("wrote %d rows to %s", len(rows), path)


def write_report(rows: list[dict[str, Any]], path: Path) -> None:
    summary = summarize_distribution([r["score"] for r in rows])
    named_hits = []
    by_date = {r["date"]: r for r in rows}
    for d, name in NAMED_CRASH_DATES.items():
        if d in by_date:
            r = by_date[d]
            named_hits.append((d, name, r["score"], r["level"], r["fired"]))

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        f.write("# CRI Backtest — 2006-2026\n\n")
        f.write(
            "Generated by `scripts/backtest_cri.py`. "
            "Re-run after any calibration change.\n\n"
        )
        f.write(f"**N days:** {summary['n']}  \n")
        f.write(f"**Date range:** {rows[0]['date']} → {rows[-1]['date']}\n\n")
        f.write("## Score distribution\n\n")
        f.write("| Stat | Value |\n|---|---|\n")
        for k in ("mean", "min", "p25", "p50", "p75", "p90", "p95", "p99", "max"):
            f.write(f"| {k} | {summary[k]:.2f} |\n")
        f.write("\n## Level distribution\n\n")
        f.write("| Level | Count | % |\n|---|---|---|\n")
        total = summary["n"]
        for lvl in ("LOW", "ELEVATED", "HIGH", "CRITICAL"):
            count = summary["level_counts"].get(lvl, 0)
            f.write(f"| {lvl} | {count} | {count / total * 100:.1f}% |\n")
        f.write("\n## Named crash dates\n\n")
        f.write("| Date | Event | CRI score | Level | Trigger fired |\n")
        f.write("|---|---|---|---|---|\n")
        for d, name, score, level, fired in named_hits:
            f.write(f"| {d} | {name} | {score:.1f} | {level} | {fired} |\n")
        if not named_hits:
            f.write("| _no aligned data for any named date_ | | | | |\n")
    log.info("wrote report to %s", path)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    p = argparse.ArgumentParser()
    p.add_argument("--start", default="2006-01-01")
    p.add_argument("--end", default=_date.today().isoformat())
    p.add_argument("--out-csv", default="docs/research/regime/cri-backtest.csv")
    p.add_argument("--out-md", default="docs/research/regime/cri-backtest.md")
    args = p.parse_args()

    start = _date.fromisoformat(args.start)
    end = _date.fromisoformat(args.end)

    settings = Settings.from_env()
    with psycopg.connect(settings.db_dsn()) as conn:
        aligned, dates = fetch_aligned_series(conn, settings.db_schema, start, end)
    log.info("aligned %d trading days", len(dates))

    # rolling_compute defaults to a 150-day window — guard against the case
    # where we have enough data for the MA+VOL minimum but not enough for the
    # rolling lookback, which would silently produce zero rows and crash
    # write_report on `rows[0]`.
    rolling_window = 150
    min_required = max(
        rolling_window + 1, cri_scoring.MA_WINDOW + cri_scoring.VOL_WINDOW
    )
    if len(dates) < min_required:
        log.error(
            "not enough data: %d days, need at least %d", len(dates), min_required
        )
        return 1

    rows = rolling_compute(aligned, dates, window=rolling_window)
    if not rows:
        log.error("rolling_compute produced no rows — check window/data alignment")
        return 1
    write_csv(rows, _PROJECT_ROOT / args.out_csv)
    write_report(rows, _PROJECT_ROOT / args.out_md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
