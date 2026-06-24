"""RUT put-calendar — ITERATION 2: hold the long leg longer, decouple the legs.

Change vs iteration 1: the long put is a LONGER-DATED standing hedge (held for
quarters, rolled near expiry), and the short is an INDEPENDENT daily OTM roll
re-struck to its own delta off current spot (capped at the long strike → still
defined-risk). "Not a group" → P&L is reported per leg: does the short income
stream finance the long hedge's carry?

Hypotheses tested:
  (a) longer long ⇒ lower daily theta carry + far fewer long rolls ⇒ lower
      breakeven front_vol_mult and much smaller drawdown.  [confirmed]
  (b) longer long ⇒ more vega held ⇒ the 2010–24 vol decline bleeds it.
The daily-short slippage wall is UNCHANGED (short cadence is still daily), so the
cost sweep is the decider — see iter2_cost_*.csv.

Persists:
  docs/research/rut-calendar/iter2_sweep_{index}.csv   — grid + per-leg decomposition
  docs/research/rut-calendar/iter2_cost_{index}.csv     — Sharpe vs slippage (best configs)

Reproduce:
  uv run python scripts/research/rut_calendar_iter2.py [INDEX]   # default RUT
"""

from __future__ import annotations

import csv
import math
import pathlib
import sys
from datetime import date
from statistics import fmean, pstdev

import psycopg

from uw_scan.config import Settings
from uw_scan.reports.put_calendar import CalendarConfig, simulate
from uw_scan.reports.vrp_macro_drawdown import load_index_vol
from uw_scan.reports.vrp_structure import CostModel
from uw_scan.storage.repository import Repository

MIN_DATE = date(2010, 9, 1)
STRESS_YEARS = {2008, 2009, 2011, 2015, 2018, 2020, 2022}

LONG_DTE = (45, 60, 90, 120, 180, 252)
SHORT_DELTA = (0.10, 0.20, 0.30)
FRONT_VOL_MULT = (0.85, 1.00, 1.10, 1.20, 1.30)
MIN_RESIDUAL = 21  # roll the long at 21 DTE — avoid the gamma/decay cliff
BASE_COST = CostModel(per_contract=0.65, slippage_frac=0.05, slippage_min=0.02)
SLIPPAGE = (0.0, 0.02, 0.05, 0.10, 0.20)
SPLIT = date(2019, 1, 1)  # train < SPLIT (in-sample) / test >= SPLIT (out-of-sample)

OUT_DIR = pathlib.Path("docs/research/rut-calendar")

FIELDS = [
    "long_dte",
    "short_delta",
    "front_vol_mult",
    "n_days",
    "sharpe",
    "ann_return",
    "maxdd_frac",
    "win_rate",
    "short_itm_rate",
    "short_leg_sharpe",
    "short_leg_ann_return",
    "long_leg_ann_return",
    "worst_year_sharpe",
    "stress_year_sharpe_mean",
]


def _stress_mean(ys: dict) -> float | None:
    vals = [s for y, s in ys.items() if y in STRESS_YEARS]
    return sum(vals) / len(vals) if vals else None


def _sharpe(series: list[float]) -> float:
    if len(series) > 1 and pstdev(series) > 0:
        return fmean(series) / pstdev(series) * math.sqrt(252)
    return 0.0


def _maxdd(series: list[float]) -> float:
    eq = peak = mdd = 0.0
    for v in series:
        eq += v
        peak = max(peak, eq)
        mdd = min(mdd, eq - peak)
    return mdd


def _breakeven(pts: list[tuple[float, float]]) -> float | None:
    pts = sorted(pts)
    for (x0, y0), (x1, y1) in zip(pts, pts[1:], strict=False):
        if y0 <= 0 <= y1 and y1 != y0:
            return x0 + (x1 - x0) * (0 - y0) / (y1 - y0)
    return None


def main() -> None:
    index = (sys.argv[1] if len(sys.argv) > 1 else "RUT").upper()
    settings = Settings.from_env()
    conn = psycopg.connect(settings.db_dsn())
    repo = Repository(conn, schema=settings.db_schema)
    loaded = load_index_vol(repo, index)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(
        f"ITERATION 2 (decoupled) INDEX={index}  {loaded.adj[0][0]}..{loaded.adj[-1][0]}"
    )

    rows: list[dict] = []
    for ld in LONG_DTE:
        for sd in SHORT_DELTA:
            for fvm in FRONT_VOL_MULT:
                cfg = CalendarConfig(
                    front_dte=1,
                    long_dte=ld,
                    short_delta=sd,
                    mode="decoupled",
                    front_vol_mult=fvm,
                    min_residual_days=MIN_RESIDUAL,
                )
                m = simulate(loaded, cfg, BASE_COST, min_date=MIN_DATE)
                rows.append(
                    {
                        "long_dte": ld,
                        "short_delta": sd,
                        "front_vol_mult": fvm,
                        "stress_year_sharpe_mean": _stress_mean(
                            m.get("year_sharpe", {})
                        ),
                        **{k: m.get(k) for k in FIELDS if k in m},
                    }
                )

    sweep_csv = OUT_DIR / f"iter2_sweep_{index.lower()}.csv"
    with sweep_csv.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="raise")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in FIELDS})

    # --- cost sweep on the best configs (by full-sample Sharpe at fvm=1.10) ---
    at110 = [r for r in rows if r["front_vol_mult"] == 1.10 and r["sharpe"] is not None]
    best = sorted(at110, key=lambda r: r["sharpe"], reverse=True)[:3]
    cost_rows: list[dict] = []
    for r in best:
        for slip in SLIPPAGE:
            cost = CostModel(per_contract=0.65, slippage_frac=slip, slippage_min=0.0)
            cfg = CalendarConfig(
                front_dte=1,
                long_dte=r["long_dte"],
                short_delta=r["short_delta"],
                mode="decoupled",
                front_vol_mult=1.10,
                min_residual_days=MIN_RESIDUAL,
            )
            m = simulate(loaded, cfg, cost, min_date=MIN_DATE)
            cost_rows.append(
                {
                    "long_dte": r["long_dte"],
                    "short_delta": r["short_delta"],
                    "slippage": slip,
                    "sharpe": m["sharpe"],
                    "ann_return": m["ann_return"],
                    "maxdd_frac": m["maxdd_frac"],
                }
            )
    cost_csv = OUT_DIR / f"iter2_cost_{index.lower()}.csv"
    with cost_csv.open("w", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "long_dte",
                "short_delta",
                "slippage",
                "sharpe",
                "ann_return",
                "maxdd_frac",
            ],
        )
        w.writeheader()
        w.writerows(cost_rows)

    # --- holdout: split each config's continuous return stream at SPLIT ---
    hold_rows: list[dict] = []
    for ld in LONG_DTE:
        for sd in SHORT_DELTA:
            cfg = CalendarConfig(
                front_dte=1,
                long_dte=ld,
                short_delta=sd,
                mode="decoupled",
                front_vol_mult=1.10,
                min_residual_days=MIN_RESIDUAL,
            )
            m = simulate(loaded, cfg, BASE_COST, min_date=MIN_DATE)
            is_r = [
                r
                for d, r in zip(m["daily_dt"], m["daily_ret"], strict=True)
                if d < SPLIT
            ]
            oos_r = [
                r
                for d, r in zip(m["daily_dt"], m["daily_ret"], strict=True)
                if d >= SPLIT
            ]
            hold_rows.append(
                {
                    "long_dte": ld,
                    "short_delta": sd,
                    "is_sharpe": _sharpe(is_r),
                    "oos_sharpe": _sharpe(oos_r),
                    "is_maxdd": _maxdd(is_r),
                    "oos_maxdd": _maxdd(oos_r),
                }
            )
    hold_csv = OUT_DIR / f"iter2_holdout_{index.lower()}.csv"
    with hold_csv.open("w", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "long_dte",
                "short_delta",
                "is_sharpe",
                "oos_sharpe",
                "is_maxdd",
                "oos_maxdd",
            ],
        )
        w.writeheader()
        w.writerows(hold_rows)

    # --- report ---
    print(f"\nWrote {len(rows)} configs → {sweep_csv}")
    print(f"Wrote {len(cost_rows)} cost rows → {cost_csv}")
    print(f"Wrote {len(hold_rows)} holdout rows → {hold_csv}\n")

    print(
        "DECOMPOSITION — combined vs short-stream vs long-carry (at front_vol_mult=1.10)"
    )
    print(
        f"{'ld':>4} {'sd':>5} {'comb_Sh':>8} {'short_Sh':>8} {'shortAnn%':>9} "
        f"{'longAnn%':>8} {'maxDD%':>7} {'stressμ':>7}"
    )
    for r in rows:
        if r["front_vol_mult"] != 1.10:
            continue
        print(
            f"{r['long_dte']:>4} {r['short_delta']:>5.2f} {r['sharpe'] or 0:>8.2f} "
            f"{r['short_leg_sharpe'] or 0:>8.2f} {(r['short_leg_ann_return'] or 0) * 100:>9.1f} "
            f"{(r['long_leg_ann_return'] or 0) * 100:>8.1f} {(r['maxdd_frac'] or 0) * 100:>7.0f} "
            f"{(r['stress_year_sharpe_mean'] or 0):>7.2f}"
        )

    print("\nBREAKEVEN front_vol_mult per (long_dte, short_delta)  [iter-1 mid≈1.16]")
    combos: dict[tuple, list] = {}
    for r in rows:
        if r["sharpe"] is not None:
            combos.setdefault((r["long_dte"], r["short_delta"]), []).append(
                (r["front_vol_mult"], r["sharpe"])
            )
    print(f"{'ld':>4} {'sd':>5} {'breakeven':>10}")
    for k in sorted(combos):
        be = _breakeven(combos[k])
        print(
            f"{k[0]:>4} {k[1]:>5.2f} {be:>10.3f}"
            if be
            else f"{k[0]:>4} {k[1]:>5.2f} {'none':>10}"
        )

    print("\nCOST — Sharpe vs slippage on the 3 best configs (front_vol_mult=1.10)")
    print(f"{'ld':>4} {'sd':>5} {'slip':>5} {'sharpe':>7} {'annR%':>6} {'maxDD%':>7}")
    for r in cost_rows:
        print(
            f"{r['long_dte']:>4} {r['short_delta']:>5.2f} {r['slippage']:>5.2f} "
            f"{r['sharpe'] or 0:>7.2f} {(r['ann_return'] or 0) * 100:>6.1f} {(r['maxdd_frac'] or 0) * 100:>7.0f}"
        )

    print(
        f"\nHOLDOUT — in-sample (<{SPLIT}) vs out-of-sample (>={SPLIT}), fvm=1.10, 5% slip"
    )
    print(
        f"{'ld':>4} {'sd':>5} {'IS_Sh':>7} {'OOS_Sh':>7} {'IS_DD%':>7} {'OOS_DD%':>7}"
    )
    for r in sorted(hold_rows, key=lambda x: x["oos_sharpe"], reverse=True):
        print(
            f"{r['long_dte']:>4} {r['short_delta']:>5.2f} {r['is_sharpe']:>7.2f} "
            f"{r['oos_sharpe']:>7.2f} {r['is_maxdd'] * 100:>7.0f} {r['oos_maxdd'] * 100:>7.0f}"
        )


if __name__ == "__main__":
    main()
