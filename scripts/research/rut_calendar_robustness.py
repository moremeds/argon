"""RUT put-calendar robustness — step 2: is any apparent edge real & robust?

Three fragilities decide this strategy, tested here on real RUT (IWM cross-check
via INDEX arg):

  1. ASSUMPTION  — edge vs front_vol_mult (front IV / RVX), the unobservable knob.
  2. SAMPLING    — block-bootstrap Sharpe CI (Politis-Romano) over 16y of months.
                   If the CI straddles 0, the "edge" is indistinguishable from luck.
  3. COST        — Sharpe vs slippage (0/1DTE OTM RUT spreads are wide).

Representative configs (front_dte=1; 0DTE never cleared the sweep grid):
  - mid     : long_dte=30, short_delta=0.20  (the sensible base)
  - long    : long_dte=45, short_delta=0.20
  - winner  : long_dte=7,  short_delta=0.30  (the Sharpe~10 sweep "winner" — shown
              here to be a 2-day-cycle artifact, near-naked, not alpha)

Persists the FULL trace:
  docs/research/rut-calendar/robustness.csv         — one row per (config, axis, point)
  docs/research/rut-calendar/robustness_trials.csv  — every bootstrap trial Sharpe

Reproduce:
  uv run python scripts/research/rut_calendar_robustness.py [INDEX]   # default RUT
"""

from __future__ import annotations

import csv
import pathlib
import sys
from datetime import date

import psycopg

from uw_scan.config import Settings
from uw_scan.reports.put_calendar import CalendarConfig, simulate
from uw_scan.reports.vrp_macro_drawdown import load_index_vol
from uw_scan.reports.vrp_robustness import mc_block_bootstrap
from uw_scan.reports.vrp_structure import CostModel
from uw_scan.storage.repository import Repository

MIN_DATE = date(2010, 9, 1)
SEED = 20260623
N_TRIALS = 2000
STRESS_YEARS = {2008, 2009, 2011, 2015, 2018, 2020, 2022}

CONFIGS = {
    "mid": dict(front_dte=1, long_dte=30, short_delta=0.20),
    "long": dict(front_dte=1, long_dte=45, short_delta=0.20),
    "winner": dict(front_dte=1, long_dte=7, short_delta=0.30),
}
# Plausibility band for front 1-day put IV vs the ~30-day RVX anchor.
FVM_BAND = (1.00, 1.10, 1.20, 1.30)
SLIPPAGE = (0.0, 0.02, 0.05, 0.10, 0.20)
BASE_COST = CostModel(per_contract=0.65, slippage_frac=0.05, slippage_min=0.02)

OUT_DIR = pathlib.Path("docs/research/rut-calendar")


def _monthly(m: dict) -> list[float]:
    """Aggregate the daily-return series to monthly sums (for the √12 bootstrap)."""
    by_month: dict[tuple[int, int], float] = {}
    for d, r in zip(m["daily_dt"], m["daily_ret"], strict=True):
        by_month[(d.year, d.month)] = by_month.get((d.year, d.month), 0.0) + r
    return [by_month[k] for k in sorted(by_month)]


def _stress_worst(m: dict) -> float | None:
    ys = m.get("year_sharpe", {}) or {}
    vals = [s for y, s in ys.items() if y in STRESS_YEARS]
    return min(vals) if vals else None


def main() -> None:
    index = (sys.argv[1] if len(sys.argv) > 1 else "RUT").upper()
    settings = Settings.from_env()
    conn = psycopg.connect(settings.db_dsn())
    repo = Repository(conn, schema=settings.db_schema)
    loaded = load_index_vol(repo, index)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    trial_rows: list[dict] = []

    for name, base in CONFIGS.items():
        # --- axis 1: ASSUMPTION (front_vol_mult) + axis 2: SAMPLING (bootstrap) ---
        for fvm in FVM_BAND:
            cfg = CalendarConfig(mode="calendar", front_vol_mult=fvm, **base)
            m = simulate(loaded, cfg, BASE_COST, min_date=MIN_DATE)
            monthly = _monthly(m)
            boot = mc_block_bootstrap(
                monthly, n_trials=N_TRIALS, mean_block=6.0, seed=SEED
            )
            tvals = [
                t["value"] for t in boot.get("trials", []) if t["value"] == t["value"]
            ]
            frac_pos = sum(1 for v in tvals if v > 0) / len(tvals) if tvals else None
            rows.append(
                {
                    "config": name,
                    "index": index,
                    "axis": "fvm",
                    "point": fvm,
                    "sharpe": m["sharpe"],
                    "ann_return": m["ann_return"],
                    "maxdd_frac": m["maxdd_frac"],
                    "worst_year_sharpe": m["worst_year_sharpe"],
                    "stress_worst_sharpe": _stress_worst(m),
                    "boot_p5": boot.get("p5"),
                    "boot_p50": boot.get("median"),
                    "boot_p95": boot.get("p95"),
                    "boot_frac_pos": frac_pos,
                }
            )
            for t in boot.get("trials", []):
                trial_rows.append(
                    {
                        "config": name,
                        "fvm": fvm,
                        "trial": t["trial"],
                        "sharpe": t["value"],
                    }
                )

        # --- axis 3: COST (slippage) at a fixed plausible fvm=1.10 ---
        for slip in SLIPPAGE:
            cost = CostModel(per_contract=0.65, slippage_frac=slip, slippage_min=0.0)
            cfg = CalendarConfig(mode="calendar", front_vol_mult=1.10, **base)
            m = simulate(loaded, cfg, cost, min_date=MIN_DATE)
            rows.append(
                {
                    "config": name,
                    "index": index,
                    "axis": "slippage",
                    "point": slip,
                    "sharpe": m["sharpe"],
                    "ann_return": m["ann_return"],
                    "maxdd_frac": m["maxdd_frac"],
                    "worst_year_sharpe": m["worst_year_sharpe"],
                    "stress_worst_sharpe": _stress_worst(m),
                }
            )

    fields = [
        "config",
        "index",
        "axis",
        "point",
        "sharpe",
        "ann_return",
        "maxdd_frac",
        "worst_year_sharpe",
        "stress_worst_sharpe",
        "boot_p5",
        "boot_p50",
        "boot_p95",
        "boot_frac_pos",
    ]
    out = OUT_DIR / f"robustness_{index.lower()}.csv"
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in fields})
    tout = OUT_DIR / f"robustness_trials_{index.lower()}.csv"
    with tout.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["config", "fvm", "trial", "sharpe"])
        w.writeheader()
        w.writerows(trial_rows)

    print(f"\nINDEX={index}  wrote {len(rows)} rows → {out}")
    print(f"  {len(trial_rows)} bootstrap trials → {tout}\n")

    print("ASSUMPTION + SAMPLING — Sharpe & block-bootstrap 90% CI per front_vol_mult")
    print(
        f"{'config':>7} {'fvm':>5} {'sharpe':>7} {'boot_p5':>8} {'boot_p50':>8} "
        f"{'boot_p95':>8} {'fracPos':>7} {'stressWorst':>11}"
    )
    for r in rows:
        if r["axis"] != "fvm":
            continue
        print(
            f"{r['config']:>7} {r['point']:>5.2f} {r['sharpe'] or 0:>7.2f} "
            f"{r['boot_p5'] or 0:>8.2f} {r['boot_p50'] or 0:>8.2f} {r['boot_p95'] or 0:>8.2f} "
            f"{r['boot_frac_pos'] or 0:>7.2f} {r['stress_worst_sharpe'] or 0:>11.2f}"
        )

    print("\nCOST — Sharpe vs slippage (front_vol_mult fixed at 1.10)")
    print(f"{'config':>7} {'slip':>5} {'sharpe':>7} {'annR%':>6}")
    for r in rows:
        if r["axis"] != "slippage":
            continue
        print(
            f"{r['config']:>7} {r['point']:>5.2f} {r['sharpe'] or 0:>7.2f} "
            f"{(r['ann_return'] or 0) * 100:>6.1f}"
        )


if __name__ == "__main__":
    main()
