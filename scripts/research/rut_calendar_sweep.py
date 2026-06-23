"""RUT put-calendar sweep — step 1: find the sweet spot (if any).

Strategy: SELL a 0/1DTE put, BUY a longer-dated put (same strike = calendar),
rolled daily. Model-priced on IWM spot + RVX vol (the only daily Russell data;
there are NO historical RUT chains). Every premium is Black-Scholes, so the
result is conditional on `front_vol_mult` (front IV vs RVX) — the one thing we
cannot observe at daily resolution. The headline output is therefore the
BREAKEVEN front_vol_mult: how much richer than RVX the front put must be for the
edge to exist. See docs/research/rut-calendar/README.md for the verdict.

Persists the FULL result set:
  docs/research/rut-calendar/sweep.csv          — one row per config, all metrics
  docs/research/rut-calendar/sweep_by_year.csv  — one row per (config, year)

Reproduce:
  uv run python scripts/research/rut_calendar_sweep.py [INDEX]   # default RUT
(reads INDEX spot + RVX from the configured DB/lake; ~16y, 2010-09 → present.
 INDEX ∈ {RUT, IWM} — RUT is the actual index; IWM is the ETF proxy.)
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
from uw_scan.reports.vrp_structure import CostModel
from uw_scan.storage.repository import Repository

# Stress years (shared with vrp_macro_drawdown) — equity drawdown / vol spikes.
STRESS_YEARS = {2008, 2009, 2011, 2015, 2018, 2020, 2022}

MIN_DATE = date(2010, 9, 1)  # clear the 252d RVX-z warmup for a clean common start

FRONT_DTE = (0, 1)
LONG_DTE = (7, 14, 21, 30, 45, 60)
SHORT_DELTA = (0.10, 0.20, 0.30)
FRONT_VOL_MULT = (0.85, 1.00, 1.15, 1.30, 1.50)

# IWM/RUT options: liquid but 0/1DTE wings carry real spread. 5% half-spread on
# premium (= 10% round-trip) + $0.65/contract. Cost sensitivity is step 2.
COST = CostModel(per_contract=0.65, slippage_frac=0.05, slippage_min=0.02)

OUT_DIR = pathlib.Path("docs/research/rut-calendar")

SCALAR_FIELDS = [
    "front_dte",
    "long_dte",
    "short_delta",
    "front_vol_mult",
    "n_days",
    "start",
    "end",
    "sharpe",
    "ann_return",
    "ann_vol",
    "maxdd_frac",
    "win_rate",
    "short_itm_rate",
    "mean_short_prem",
    "mean_long_decay",
    "net_theta",
    "worst_year_sharpe",
    "stress_year_sharpe_mean",
]


def _stress_mean(year_sharpe: dict[int, float]) -> float | None:
    vals = [s for y, s in year_sharpe.items() if y in STRESS_YEARS]
    return sum(vals) / len(vals) if vals else None


def _breakeven_fvm(rows_for_combo: list[dict]) -> float | None:
    """Linear-interpolate the front_vol_mult where Sharpe crosses 0."""
    pts = sorted(
        (r["front_vol_mult"], r["sharpe"])
        for r in rows_for_combo
        if r["sharpe"] is not None
    )
    for (x0, y0), (x1, y1) in zip(pts, pts[1:], strict=False):
        if y0 <= 0 <= y1 and y1 != y0:
            return x0 + (x1 - x0) * (0 - y0) / (y1 - y0)
    return None


def main() -> None:
    index = (sys.argv[1] if len(sys.argv) > 1 else "RUT").upper()
    sweep_csv = OUT_DIR / f"sweep_{index.lower()}.csv"
    year_csv = OUT_DIR / f"sweep_by_year_{index.lower()}.csv"

    settings = Settings.from_env()
    conn = psycopg.connect(settings.db_dsn())
    repo = Repository(conn, schema=settings.db_schema)
    loaded = load_index_vol(repo, index)
    print(
        f"INDEX={index}  ({len(loaded.adj)} days, {loaded.adj[0][0]} .. {loaded.adj[-1][0]})"
    )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    year_rows: list[dict] = []

    for fd in FRONT_DTE:
        for ld in LONG_DTE:
            for sd in SHORT_DELTA:
                for fvm in FRONT_VOL_MULT:
                    cfg = CalendarConfig(
                        front_dte=fd,
                        long_dte=ld,
                        short_delta=sd,
                        mode="calendar",
                        front_vol_mult=fvm,
                    )
                    m = simulate(loaded, cfg, COST, min_date=MIN_DATE)
                    ys = m.get("year_sharpe", {}) or {}
                    row = {
                        "front_dte": fd,
                        "long_dte": ld,
                        "short_delta": sd,
                        "front_vol_mult": fvm,
                        "stress_year_sharpe_mean": _stress_mean(ys),
                        **{k: m.get(k) for k in SCALAR_FIELDS if k in m},
                    }
                    rows.append(row)
                    for y, s in sorted(ys.items()):
                        year_rows.append(
                            {
                                "front_dte": fd,
                                "long_dte": ld,
                                "short_delta": sd,
                                "front_vol_mult": fvm,
                                "year": y,
                                "year_sharpe": s,
                                "stress": int(y in STRESS_YEARS),
                            }
                        )

    with sweep_csv.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=SCALAR_FIELDS, extrasaction="raise")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in SCALAR_FIELDS})
    with year_csv.open("w", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "front_dte",
                "long_dte",
                "short_delta",
                "front_vol_mult",
                "year",
                "year_sharpe",
                "stress",
            ],
        )
        w.writeheader()
        w.writerows(year_rows)

    # --- report ---
    print(f"\nWrote {len(rows)} configs → {sweep_csv}")
    print(f"Wrote {len(year_rows)} config-years → {year_csv}\n")

    ranked = sorted(
        (r for r in rows if r["sharpe"] is not None),
        key=lambda r: r["sharpe"],
        reverse=True,
    )
    print("TOP 12 BY FULL-SAMPLE SHARPE")
    print(
        f"{'fd':>3} {'ld':>3} {'sd':>5} {'fvm':>5} {'sharpe':>7} "
        f"{'annR%':>6} {'maxDD%':>7} {'worstYr':>7} {'stressμ':>7} {'ITM%':>5}"
    )
    for r in ranked[:12]:
        print(
            f"{r['front_dte']:>3} {r['long_dte']:>3} {r['short_delta']:>5.2f} "
            f"{r['front_vol_mult']:>5.2f} {r['sharpe']:>7.2f} "
            f"{(r['ann_return'] or 0) * 100:>6.1f} {(r['maxdd_frac'] or 0) * 100:>7.0f} "
            f"{r['worst_year_sharpe'] or 0:>7.2f} "
            f"{(r['stress_year_sharpe_mean'] or 0):>7.2f} "
            f"{(r['short_itm_rate'] or 0) * 100:>5.1f}"
        )

    print(
        "\nBREAKEVEN front_vol_mult (Sharpe=0) per (front_dte, long_dte, short_delta)"
    )
    print(f"{'fd':>3} {'ld':>3} {'sd':>5} {'breakeven_fvm':>14}")
    combos: dict[tuple, list[dict]] = {}
    for r in rows:
        combos.setdefault((r["front_dte"], r["long_dte"], r["short_delta"]), []).append(
            r
        )
    for key in sorted(combos):
        be = _breakeven_fvm(combos[key])
        be_s = f"{be:.3f}" if be is not None else "  none in grid"
        print(f"{key[0]:>3} {key[1]:>3} {key[2]:>5.2f} {be_s:>14}")


if __name__ == "__main__":
    main()
