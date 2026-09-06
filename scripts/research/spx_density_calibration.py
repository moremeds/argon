#!/usr/bin/env python
"""Historical calibration 复盘 of the SPX 1-5 day density cone (GJR-GARCH Monte Carlo).

`uw_scan.spx_density_forecast` settles each row with exactly two numbers:
`realised_return` and `inside_band80` (see
`worker/jobs/spx_density_forecast.py::_settle_pass`). That answers "did the 80%
band contain the outcome" and nothing else — it cannot say whether the 50% and
90% bands are calibrated too, whether the whole predictive DISTRIBUTION is
honest, whether the GJR cone beats its own EWMA baseline, or whether the sign
call is worth anything. This script computes those and persists them.

What it measures, per (origin, h) / per h pooled / per origin pooled:

* Coverage at 50% (q25-q75), 80% (q10-q90) and 90% (q05-q95), each with a
  Wilson 95% interval, for the model AND for the stored `baseline_q*` (arm-A
  EWMA) quantiles. Wilson rather than the normal approximation because n per
  cell is ~40-80 and coverage sits near 0.8-0.9, where the normal interval
  crosses 1.0 and stops meaning anything.
* Pinball (quantile) loss per quantile level, model and baseline, plus the
  model/baseline ratio. Coverage is a hit/miss test and throws away the size of
  the miss; pinball is the proper scoring rule for a quantile and does not.
  Ratio < 1 = the GJR cone beats the EWMA baseline at that level.
* PIT u = F(realised) read off `density_bins_jsonb` — the actual Monte-Carlo
  histogram, not a Gaussian fitted through the quantiles. Decile histogram plus
  a one-sample KS test against Uniform(0,1). Coverage checks three points of
  the CDF; PIT checks all of it.
* P(down) = F(0) from the same bins, scored by Brier against the realised sign,
  next to the neutral-0.5 Brier (0.25) for reference.

CAVEATS — binding on every number below:

1. OVERLAPPING WINDOWS. For h > 1 the target windows of consecutive as_of
   sessions overlap (an h=5 cone issued Monday and one issued Tuesday share
   four of five trading days). The rows are therefore NOT independent and the
   effective n is materially smaller than the reported n — roughly n/h for the
   pooled-per-h cells. No correction is attempted: the Wilson intervals and the
   KS p-value are reported as-is and are OPTIMISTIC (too narrow / too small).
   Treat them as ordering aids, not as tests.
2. ORIGIN IS NOT A COSMETIC SPLIT. `origin='reconstructed'` rows (2026-05-05..
   2026-08-14) were written by a backfill in 2026-08, replaying what the model
   would have issued that night. The replay is genuinely point-in-time — the
   panel rail in `density/forecast.py` pins the index frame and the seed — but
   it was still run with knowledge that the window existed and is not an
   out-of-sample record. `origin='prospective'` rows were issued forward, one
   per night, before the outcome existed. Only the prospective cells are a
   live track record, and there are few of them (h=1: 18 rows). Every table
   below reports the split; do not read the pooled row as a track record.
3. TAIL RESOLUTION IN THE PIT. `_density_bins` clips the histogram axis to the
   (0.005, 0.995) quantiles of the draws and records only the TOTAL number of
   excluded draws (`clipped`), not the below/above split. Because the clip is
   symmetric by construction the split is taken as clipped/2 each side, and a
   realisation outside [lo, hi] gets the midpoint of the unresolvable tail
   interval. The count of such rows is reported per cell as
   `pit_n_below_lo` / `pit_n_above_hi`; over the whole table it is 6 of 400.

Reproduce:
    UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard \\
    UW_SCAN_DB_USER=argon_app UW_SCAN_DB_SCHEMA=uw_scan \\
    UW_SCAN_DB_PASSWORD=<mini /opt/argon/.env> UW_SCAN_API_KEY=<any> \\
    uv run python scripts/research/spx_density_calibration.py

Reads:  uw_scan.spx_density_forecast (settled rows only; never written to)
Writes: uw_scan.backtest_sweep_runs / _results, strategy='spx_density_calibration'
"""

from __future__ import annotations

import logging
import math
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

import psycopg
from scipy import stats

from uw_scan.backtest import run_sweep
from uw_scan.config import Settings
from uw_scan.storage.backtest_repository import BacktestRepository

log = logging.getLogger("spx_density_calibration")

STRATEGY = "spx_density_calibration"
REPRODUCE = "uv run python scripts/research/spx_density_calibration.py"

# The cone's own quantile grid (density/constants.QUANTILES), as (level, column stem).
LEVELS: tuple[tuple[float, str], ...] = (
    (0.05, "q05"),
    (0.10, "q10"),
    (0.25, "q25"),
    (0.50, "q50"),
    (0.75, "q75"),
    (0.90, "q90"),
    (0.95, "q95"),
)

# (nominal coverage, lower column stem, upper column stem)
BANDS: tuple[tuple[int, str, str], ...] = (
    (50, "q25", "q75"),
    (80, "q10", "q90"),
    (90, "q05", "q95"),
)

PIT_DECILES = 10


# --------------------------------------------------------------------------------------
# pure metric math (imported by tests/unit/scripts/test_spx_density_calibration.py)
# --------------------------------------------------------------------------------------


def pinball_loss(tau: float, q: float, y: float) -> float:
    """Quantile (pinball) loss of a forecast quantile `q` at level `tau` vs outcome `y`.

    Under-prediction (y > q) costs tau * (y - q); over-prediction costs
    (1 - tau) * (q - y). Minimised in expectation by the true tau-quantile,
    which is what makes it the proper score for this object.
    """
    d = y - q
    return tau * d if d >= 0 else (tau - 1.0) * d


def wilson_ci(k: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion k/n. (nan, nan) when n == 0."""
    if n <= 0:
        return (float("nan"), float("nan"))
    p = k / n
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = (z / denom) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, centre - half), min(1.0, centre + half))


def pit_from_bins(bins: Mapping, x: float) -> tuple[float, str]:
    """PIT value u = F(x) from a stored `density_bins_jsonb` histogram.

    Follows `density/forecast._density_bins` exactly: `counts` covers [lo, hi]
    only, `total` is every finite draw, and `total - sum(counts)` draws were
    clipped off the axis by the symmetric (0.005, 0.995) clip — counted, never
    dropped. Half of them are taken to sit below `lo` and half above `hi`,
    which is what a symmetric clip means; see caveat 3 in the module docstring.

    Returns (u, status) with status in {'inside', 'below_lo', 'above_hi'}. A
    realisation outside the axis gets the midpoint of the tail interval it is
    known to lie in, because the histogram cannot resolve further.
    """
    counts = [int(c) for c in bins["counts"]]
    total = int(bins["total"])
    lo = float(bins["lo"])
    hi = float(bins["hi"])
    n_bins = int(bins["n_bins"])
    if total <= 0 or n_bins <= 0 or hi <= lo or len(counts) != n_bins:
        raise ValueError(f"unusable density bins: {bins!r}")

    clipped = total - sum(counts)
    below = clipped / 2.0
    above = clipped - below

    if x < lo:
        return ((below / 2.0) / total, "below_lo")
    if x > hi:
        return ((total - above / 2.0) / total, "above_hi")

    width = (hi - lo) / n_bins
    k = int((x - lo) / width)
    k = min(max(k, 0), n_bins - 1)
    frac = (x - (lo + k * width)) / width
    frac = min(max(frac, 0.0), 1.0)
    cum = below + float(sum(counts[:k])) + frac * counts[k]
    return (cum / total, "inside")


def ks_uniform(u: Sequence[float]) -> tuple[float, float]:
    """One-sample KS statistic and p-value against Uniform(0, 1)."""
    if len(u) < 2:
        return (float("nan"), float("nan"))
    res = stats.kstest(list(u), "uniform")
    return (float(res.statistic), float(res.pvalue))


# --------------------------------------------------------------------------------------
# per-row scoring
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Scored:
    as_of: date
    h: int
    origin: str
    realised: float
    covered: dict[int, bool]
    baseline_covered: dict[int, bool]
    pinball: dict[str, float]
    baseline_pinball: dict[str, float]
    pit_u: float
    pit_status: str
    p_down: float


def score_row(row: Mapping) -> Scored:
    y = float(row["realised_return"])
    q = {stem: float(row[stem]) for _, stem in LEVELS}
    b = {stem: float(row[f"baseline_{stem}"]) for _, stem in LEVELS}

    covered = {nom: (q[lo] <= y <= q[hi]) for nom, lo, hi in BANDS}
    baseline_covered = {nom: (b[lo] <= y <= b[hi]) for nom, lo, hi in BANDS}

    bins = row["density_bins_jsonb"]
    pit_u, pit_status = pit_from_bins(bins, y)
    p_down, _ = pit_from_bins(bins, 0.0)

    return Scored(
        as_of=row["as_of"],
        h=int(row["h"]),
        origin=str(row["origin"]),
        realised=y,
        covered=covered,
        baseline_covered=baseline_covered,
        pinball={stem: pinball_loss(tau, q[stem], y) for tau, stem in LEVELS},
        baseline_pinball={stem: pinball_loss(tau, b[stem], y) for tau, stem in LEVELS},
        pit_u=pit_u,
        pit_status=pit_status,
        p_down=p_down,
    )


def aggregate(rows: Sequence[Scored]) -> dict:
    """All calibration metrics for one (origin, h) cell."""
    n = len(rows)
    out: dict[str, object] = {"n": n}

    for nom, _, _ in BANDS:
        k = sum(1 for r in rows if r.covered[nom])
        kb = sum(1 for r in rows if r.baseline_covered[nom])
        lo, hi = wilson_ci(k, n)
        blo, bhi = wilson_ci(kb, n)
        out[f"coverage_{nom}"] = k / n
        out[f"coverage_{nom}_ci_lo"] = lo
        out[f"coverage_{nom}_ci_hi"] = hi
        out[f"baseline_coverage_{nom}"] = kb / n
        out[f"baseline_coverage_{nom}_ci_lo"] = blo
        out[f"baseline_coverage_{nom}_ci_hi"] = bhi

    for _, stem in LEVELS:
        m = sum(r.pinball[stem] for r in rows) / n
        bl = sum(r.baseline_pinball[stem] for r in rows) / n
        out[f"pinball_{stem}"] = m
        out[f"baseline_pinball_{stem}"] = bl
        out[f"pinball_ratio_{stem}"] = (m / bl) if bl > 0 else None
    out["pinball_mean"] = sum(
        float(out[f"pinball_{stem}"]) for _, stem in LEVELS
    ) / len(LEVELS)
    out["baseline_pinball_mean"] = sum(
        float(out[f"baseline_pinball_{stem}"]) for _, stem in LEVELS
    ) / len(LEVELS)
    out["pinball_ratio_mean"] = (
        float(out["pinball_mean"]) / float(out["baseline_pinball_mean"])
        if float(out["baseline_pinball_mean"]) > 0
        else None
    )

    us = [r.pit_u for r in rows]
    hist = [0] * PIT_DECILES
    for u in us:
        idx = min(int(u * PIT_DECILES), PIT_DECILES - 1)
        hist[idx] += 1
    ks_stat, ks_p = ks_uniform(us)
    out["pit_deciles"] = hist
    out["pit_mean"] = sum(us) / n
    out["pit_ks_stat"] = ks_stat
    out["pit_ks_pvalue"] = ks_p
    out["pit_n_below_lo"] = sum(1 for r in rows if r.pit_status == "below_lo")
    out["pit_n_above_hi"] = sum(1 for r in rows if r.pit_status == "above_hi")

    brier = sum((r.p_down - (1.0 if r.realised < 0 else 0.0)) ** 2 for r in rows) / n
    out["p_down_mean"] = sum(r.p_down for r in rows) / n
    out["realised_down_rate"] = sum(1 for r in rows if r.realised < 0) / n
    out["brier"] = brier
    out["brier_neutral"] = 0.25
    out["brier_skill_vs_neutral"] = 1.0 - brier / 0.25

    out["as_of_first"] = min(r.as_of for r in rows).isoformat()
    out["as_of_last"] = max(r.as_of for r in rows).isoformat()
    return out


# --------------------------------------------------------------------------------------
# load / group / report
# --------------------------------------------------------------------------------------

SELECT_COLS = (
    "as_of, h, origin, realised_return, density_bins_jsonb, "
    + ", ".join(stem for _, stem in LEVELS)
    + ", "
    + ", ".join(f"baseline_{stem}" for _, stem in LEVELS)
)


def load_rows(conn, schema: str) -> list[Mapping]:
    sql = f"""
        SELECT {SELECT_COLS}
          FROM {schema}.spx_density_forecast
         WHERE realised_return IS NOT NULL
           AND density_bins_jsonb IS NOT NULL
         ORDER BY as_of, h
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        cols = [c.name for c in cur.description]
        return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]


def build_groups(scored: Sequence[Scored]) -> list[tuple[dict, list[Scored]]]:
    """The three aggregations, in report order: (origin, h), h pooled, origin pooled."""
    origins = sorted({r.origin for r in scored})
    hs = sorted({r.h for r in scored})
    groups: list[tuple[dict, list[Scored]]] = []
    for origin in origins:
        for h in hs:
            sel = [r for r in scored if r.origin == origin and r.h == h]
            if sel:
                groups.append(({"origin": origin, "h": h}, sel))
    for h in hs:
        sel = [r for r in scored if r.h == h]
        if sel:
            groups.append(({"origin": "all", "h": h}, sel))
    for origin in origins:
        sel = [r for r in scored if r.origin == origin]
        if sel:
            groups.append(({"origin": origin, "h": "all"}, sel))
    return groups


def _f(v, places: int = 3) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "-"
    return f"{v:.{places}f}"


def print_tables(results: Sequence[dict]) -> None:
    print()
    print("### Coverage (model, Wilson 95% CI) vs baseline")
    print()
    print(
        "| origin | h | n | cov50 | cov80 | cov90 | base cov50 | base cov80 | base cov90 |"
    )
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for r in results:
        c, m = r["config"], r["metrics"]
        cells = []
        for nom in (50, 80, 90):
            cells.append(
                f"{_f(m[f'coverage_{nom}'])} "
                f"[{_f(m[f'coverage_{nom}_ci_lo'], 2)}, {_f(m[f'coverage_{nom}_ci_hi'], 2)}]"
            )
        for nom in (50, 80, 90):
            cells.append(_f(m[f"baseline_coverage_{nom}"]))
        print(f"| {c['origin']} | {c['h']} | {m['n']} | " + " | ".join(cells) + " |")

    print()
    print("### Pinball loss ratio, model / baseline (< 1 = GJR beats EWMA)")
    print()
    head = " | ".join(stem for _, stem in LEVELS)
    print(f"| origin | h | n | {head} | mean | mean pinball (model) |")
    print("| --- | --- | --- | " + " | ".join("---" for _ in LEVELS) + " | --- | --- |")
    for r in results:
        c, m = r["config"], r["metrics"]
        cells = [_f(m[f"pinball_ratio_{stem}"]) for _, stem in LEVELS]
        print(
            f"| {c['origin']} | {c['h']} | {m['n']} | "
            + " | ".join(cells)
            + f" | {_f(m['pinball_ratio_mean'])} | {_f(m['pinball_mean'], 5)} |"
        )

    print()
    print("### PIT uniformity and sign call")
    print()
    print(
        "| origin | h | n | PIT mean | KS stat | KS p | tails out (lo/hi) | "
        "P(down) mean | realised down | Brier | Brier skill vs 0.5 | PIT deciles |"
    )
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for r in results:
        c, m = r["config"], r["metrics"]
        print(
            f"| {c['origin']} | {c['h']} | {m['n']} | {_f(m['pit_mean'])} | "
            f"{_f(m['pit_ks_stat'])} | {_f(m['pit_ks_pvalue'])} | "
            f"{m['pit_n_below_lo']}/{m['pit_n_above_hi']} | {_f(m['p_down_mean'])} | "
            f"{_f(m['realised_down_rate'])} | {_f(m['brier'], 4)} | "
            f"{_f(m['brier_skill_vs_neutral'])} | "
            f"{','.join(str(x) for x in m['pit_deciles'])} |"
        )
    print()


NOTES = (
    "Calibration 复盘 of the SPX 1-5d density cone. Per (origin, h), per h pooled "
    "and per origin pooled: coverage at 50/80/90% with Wilson 95% CIs for the GJR "
    "cone AND the stored EWMA baseline_q*; pinball loss per quantile level for both "
    "plus the model/baseline ratio; PIT u = F(realised) read off density_bins_jsonb "
    "with a decile histogram and a one-sample KS test vs Uniform(0,1); P(down) = "
    "F(0) scored by Brier against the neutral 0.25. "
    "CAVEAT 1 - OVERLAPPING WINDOWS: for h > 1 consecutive as_of sessions share "
    "target days, so rows are not independent and effective n is roughly n/h. No "
    "correction is applied; the Wilson intervals and KS p-values are therefore "
    "optimistic (too narrow / too small) and rank rather than test. "
    "CAVEAT 2 - ORIGIN SPLIT: origin='reconstructed' rows (2026-05-05..2026-08-14) "
    "were replayed by a 2026-08 backfill - point-in-time in construction (the panel "
    "rail pins index frame and seed) but not an out-of-sample record. Only "
    "origin='prospective' rows were issued forward before the outcome existed, and "
    "there are few (h=1: 18). Read the pooled cells as description, the prospective "
    "cells as the track record. "
    "CAVEAT 3 - PIT TAILS: density_bins_jsonb clips the axis to the (0.005, 0.995) "
    "draw quantiles and stores only the total clipped count, not the below/above "
    "split; the symmetric clip is split 50/50 and an outside realisation gets the "
    "midpoint of its tail interval. Counts reported per cell as pit_n_below_lo / "
    "pit_n_above_hi (6 of 400 rows overall). "
    "Reads spx_density_forecast settled rows only; never writes to it."
)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    settings = Settings.from_env()
    sha = (
        subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True
        ).stdout.strip()
        or None
    )

    with psycopg.connect(settings.db_dsn()) as conn:
        raw = load_rows(conn, settings.db_schema)
        if not raw:
            raise SystemExit(
                "No settled spx_density_forecast rows with density bins. "
                "Nothing to calibrate."
            )
        scored = [score_row(r) for r in raw]
        log.info(
            "scored %d settled rows, %s..%s, origins=%s",
            len(scored),
            min(r.as_of for r in scored),
            max(r.as_of for r in scored),
            sorted({r.origin for r in scored}),
        )

        groups = build_groups(scored)
        by_key = {(str(c["origin"]), str(c["h"])): rows for c, rows in groups}

        out = run_sweep(
            [c for c, _ in groups],
            lambda cfg: {
                "metrics": aggregate(by_key[(str(cfg["origin"]), str(cfg["h"]))]),
                "n_trades": len(by_key[(str(cfg["origin"]), str(cfg["h"]))]),
            },
            repo=BacktestRepository(conn, schema=settings.db_schema),
            strategy=STRATEGY,
            reproduce_cmd=REPRODUCE,
            params_grid={
                "quantile_levels": [tau for tau, _ in LEVELS],
                "bands": [nom for nom, _, _ in BANDS],
                "pit_deciles": PIT_DECILES,
                "aggregations": ["origin_x_h", "h_pooled", "origin_pooled"],
            },
            git_sha=sha,
            data_start=min(r.as_of for r in scored),
            data_end=max(r.as_of for r in scored),
            notes=NOTES,
        )

    print_tables(out["results"])
    log.info("run_id=%s ok=%s error=%s", out["run_id"], out["n_ok"], out["n_error"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
