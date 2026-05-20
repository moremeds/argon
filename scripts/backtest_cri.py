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
  - docs/research/regime/oos-summary.json (with --write-oos-summary)

Usage:
  uv run python scripts/backtest_cri.py
  uv run python scripts/backtest_cri.py --start 2006-01-01 --end 2026-05-15
  uv run python scripts/backtest_cri.py --write-oos-summary
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import sys
from collections import Counter
from datetime import date as _date
from datetime import datetime as _datetime
from pathlib import Path
from typing import Any

import numpy as np
import psycopg

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from uw_scan.cards import cri_scoring  # noqa: E402
from uw_scan.config import Settings  # noqa: E402

# ── OOS label definitions (must match docs/research/regime/cri-validation.ipynb §9) ──
# label_dd5  : SPX -5%  drawdown within 20 trading days
# label_dd10 : SPX -10% drawdown within 60 trading days
OOS_LABELS: dict[str, tuple[int, float]] = {
    "dd5": (20, 0.05),
    "dd10": (60, 0.10),
}

# v1 published baselines from the notebook narrative (Section 9).
# These are the numbers v3 must not degrade below for the OOS gate to pass.
V1_AUC_BASELINE: dict[str, float] = {"dd5": 0.620, "dd10": 0.647}

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
                "composite_version": cri.get("composite_version"),
                "vix_c": cri["components"]["vix"],
                "vvix_c": cri["components"]["vvix"],
                "corr_c": cri["components"]["correlation"],
                "trend_c": cri["components"]["momentum"],
                "fired": p["crash_trigger"]["fired"],
                "vix": p["vix"],
                "vvix": p["vvix"],
                "cor1m": p["cor1m"],
                "spx_distance_pct": p["spx_distance_pct"],
                "spy": p["spy"],  # needed for forward-drawdown labels
                "pullback_20d_pct": p.get("pullback_20d_pct"),
                "vix_delta_3d": p.get("vix_delta_3d"),
            }
        )
    return out


# ══════════════════════════════════════════════════════════════════
# OOS gate: ROC-AUC of CRI score vs forward-drawdown labels
# ══════════════════════════════════════════════════════════════════


def _forward_drawdown_labels(
    closes: np.ndarray, window: int, threshold: float
) -> np.ndarray:
    """Binary label per day: 1 if the trough over the next ``window`` sessions
    is ≤ -threshold below today's close, 0 otherwise. -1 means undefined
    (last ``window`` days have no full forward window).
    """
    n = len(closes)
    labels = np.full(n, -1, dtype=int)
    for i in range(n - window):
        future = closes[i + 1 : i + 1 + window]
        if len(future) == 0:
            continue
        worst = float(future.min())
        ratio = worst / float(closes[i]) - 1.0
        labels[i] = 1 if ratio <= -threshold else 0
    return labels


def _roc_auc(y_true: np.ndarray, y_score: np.ndarray) -> float:
    """Mann-Whitney AUC via average ranks (no sklearn dependency).

    Excludes rows where y_true == -1 (undefined label) or y_score is NaN.
    """
    mask = (y_true != -1) & ~np.isnan(y_score)
    yt = y_true[mask].astype(int)
    ys = y_score[mask].astype(float)
    n_pos = int((yt == 1).sum())
    n_neg = int((yt == 0).sum())
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    # Compute average ranks (1-indexed; ties get mean rank)
    order = np.argsort(ys, kind="mergesort")
    ranks = np.empty_like(ys, dtype=float)
    n = len(ys)
    i = 0
    while i < n:
        j = i
        while j + 1 < n and ys[order[j + 1]] == ys[order[i]]:
            j += 1
        avg = (i + j + 2) / 2.0  # 1-indexed mean rank
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    sum_ranks_pos = float(ranks[yt == 1].sum())
    return (sum_ranks_pos - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)


def _compute_v3_auc(rows: list[dict[str, Any]]) -> dict[str, float]:
    """For each label in OOS_LABELS, compute v3 ROC-AUC over the backtest."""
    if not rows:
        return {}
    closes = np.array([r["spy"] for r in rows], dtype=float)
    scores = np.array([r["score"] for r in rows], dtype=float)
    auc_by_label: dict[str, float] = {}
    for name, (window, threshold) in OOS_LABELS.items():
        labels = _forward_drawdown_labels(closes, window, threshold)
        auc_by_label[name] = _roc_auc(labels, scores)
    return auc_by_label


def write_oos_summary(rows: list[dict[str, Any]], path: Path) -> None:
    """Write oos-summary.json with v1 baselines + freshly computed v3 AUC.

    Symmetric comparison: both versions are evaluated on the SAME label
    definitions (`OOS_LABELS`) which match the published notebook narrative.
    """
    v3_auc = _compute_v3_auc(rows)
    n_obs = sum(1 for r in rows if math.isfinite(r["score"]))
    payload = {
        "as_of": _datetime.now().date().isoformat(),
        "notebook": "docs/research/regime/cri-validation.ipynb",
        "method": (
            "Forward-drawdown labels: dd5 = SPX -5% within 20 sessions; "
            "dd10 = SPX -10% within 60 sessions. AUC computed via "
            "Mann-Whitney rank-sum (no sklearn dep) on the full backtest. "
            "v1 baselines are the published Section 9 numbers; v3 is "
            "freshly recomputed on the same label definitions."
        ),
        "labels": [
            {
                "name": "label_dd5",
                "definition": "SPX -5% drawdown within 20 trading days",
            },
            {
                "name": "label_dd10",
                "definition": "SPX -10% drawdown within 60 trading days",
            },
        ],
        "versions": [
            {
                "label": "CRI v1",
                "version": 1,
                "auc_dd5": V1_AUC_BASELINE["dd5"],
                "auc_dd10": V1_AUC_BASELINE["dd10"],
                "n_observations": n_obs,
                "notes": "Frozen baseline from cri-validation.ipynb §9 (pre-PR-58).",
            },
            {
                "label": "CRI v3",
                "version": 3,
                "auc_dd5": round(v3_auc.get("dd5", float("nan")), 4)
                if not math.isnan(v3_auc.get("dd5", float("nan")))
                else None,
                "auc_dd10": round(v3_auc.get("dd10", float("nan")), 4)
                if not math.isnan(v3_auc.get("dd10", float("nan")))
                else None,
                "n_observations": n_obs,
                "notes": (
                    "v3: VIX floor 13, RoC denom 40, VVIX floor 80, "
                    "tactical pullback sub-score (saturates at -4% from 20d high)."
                ),
            },
        ],
        # Legacy flat shape for the GET /api/regime/validation endpoint + ValidationTab
        # UI consumer. Mirrors `versions[]` above with the older OosScore field names.
        "scores": [
            {
                "model": "CRI v1 (frozen baseline)",
                "auc_dd5": V1_AUC_BASELINE["dd5"],
                "auc_vix30": None,
                "auc_dd10": V1_AUC_BASELINE["dd10"],
            },
            {
                "model": "CRI v3 (current)",
                "auc_dd5": round(v3_auc.get("dd5", float("nan")), 4)
                if not math.isnan(v3_auc.get("dd5", float("nan")))
                else None,
                "auc_vix30": None,
                "auc_dd10": round(v3_auc.get("dd10", float("nan")), 4)
                if not math.isnan(v3_auc.get("dd10", float("nan")))
                else None,
            },
        ],
        "ablation": [],
        "interpretation": (
            "v3 must score >= v1 on both auc_dd5 and auc_dd10 for the OOS gate "
            "to pass. The gate is enforced by tests/integration/regime/"
            "test_cri_oos_gate.py — CI will block merge on regression."
        ),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")
    log.info("wrote OOS summary to %s", path)
    log.info(
        "v3 AUC: dd5=%.4f (v1=%.3f), dd10=%.4f (v1=%.3f)",
        v3_auc.get("dd5", float("nan")),
        V1_AUC_BASELINE["dd5"],
        v3_auc.get("dd10", float("nan")),
        V1_AUC_BASELINE["dd10"],
    )


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
    p.add_argument(
        "--write-oos-summary",
        nargs="?",
        const="docs/research/regime/oos-summary.json",
        default=None,
        help="Write oos-summary.json with v1 + v3 AUC. Optional path; "
        "default docs/research/regime/oos-summary.json.",
    )
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
    if args.write_oos_summary:
        write_oos_summary(rows, _PROJECT_ROOT / args.write_oos_summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
