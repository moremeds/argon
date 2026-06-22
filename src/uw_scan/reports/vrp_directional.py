"""VRP axis C (item 5): directional VRP + ΔVRP-reversion.

- Directional (5a): does the RICH cohort OUT-RETURN the CHEAP cohort? Build a
  per-date long-short differential series d(date)=mean(RICH fwd ret)−mean(CHEAP
  fwd ret) per asset_class (NOT cross-sectionally demeaned — the documented
  Bollerslev effect is time-series/level; demeaning would strip it), and run OOS
  on the differential series itself. Both cohorts need ≥ MIN_COHORT names on a
  date for it to contribute (a one-name cohort is noise). Keyed (asset_class,
  horizon).
- ΔVRP-reversion (5b): forward ΔVRP = vrp(t+h)−vrp(t) per (asset_class,
  deviation_class, horizon). RICH should revert DOWN. Null-guarded.

Both FULL-REWRITE. Design: docs/superpowers/plans/2026-06-22-vrp-research-expansion.md
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date as _date
from typing import Any

from uw_scan.cards.skew_first_principles import asset_class_baseline
from uw_scan.reports.vrp_markout import _deviation_class, _load_vrp_series
from uw_scan.reports.vrp_markout_core import MIN_N, apply_split_adjustment, walkforward
from uw_scan.storage.repository import Repository

log = logging.getLogger(__name__)

# returns are decimals ~0.01-0.03; ΔVRP is in vol points ~0.02 (validated against
# the VRP/return-predictability literature in the research note, Task 12).
DIRECTIONAL_THRESHOLD = 0.01
DIRECTIONAL_HOLDOUT = 0.005
DVRP_THRESHOLD = 0.02
DVRP_HOLDOUT = 0.01
DEFAULT_HORIZONS = (5, 20, 60)
MIN_COHORT = 2


def _mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def _ac(repo: Repository, ticker: str) -> str:
    sector = repo.fetch_watchlist_sector(ticker)
    return asset_class_baseline(ticker, sector=sector)["asset_class"]


def run_vrp_directional(
    *,
    repo: Repository,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    min_n: int = MIN_N,
) -> dict[str, Any]:
    """Item 5a. Per-date RICH−CHEAP forward-return differential series, OOS on the
    differential. Full-rewrite vrp_directional_verdicts."""
    today = _date.today()
    repo.clear_vrp_directional_verdicts()
    written = 0
    for h in horizons:
        # pass 1: per (asset_class, date) collect RICH/CHEAP forward returns.
        cohorts: dict[tuple[str, _date], dict[str, list[float]]] = defaultdict(
            lambda: {"RICH": [], "CHEAP": []}
        )
        rich_all: dict[str, list[float]] = defaultdict(list)
        cheap_all: dict[str, list[float]] = defaultdict(list)
        for ticker in repo.fetch_distinct_vrp_tickers():
            rows = _load_vrp_series(repo, ticker)
            if not rows:
                continue
            asset_class = _ac(repo, ticker)
            adj = apply_split_adjustment(
                repo.fetch_price_series(ticker), repo.fetch_corporate_actions(ticker)
            )
            if not adj:
                continue
            pidx = {d: k for k, (d, _v) in enumerate(adj)}
            for r in rows:
                z = r["vrp_z_20"]
                if z is None:
                    continue
                dev = _deviation_class(float(z))
                if dev not in ("RICH", "CHEAP"):
                    continue
                pi = pidx.get(r["market_date"])
                if pi is None or pi + h >= len(adj):
                    continue
                p0, p1 = adj[pi][1], adj[pi + h][1]
                if p0 <= 0:
                    continue
                ret = p1 / p0 - 1.0
                cohorts[(asset_class, r["market_date"])][dev].append(ret)
                (rich_all if dev == "RICH" else cheap_all)[asset_class].append(ret)
        # pass 2: per-date differential where BOTH cohorts have >= MIN_COHORT names.
        obs_by_ac: dict[str, list[dict]] = defaultdict(list)
        for (asset_class, d), c in cohorts.items():
            if len(c["RICH"]) >= MIN_COHORT and len(c["CHEAP"]) >= MIN_COHORT:
                obs_by_ac[asset_class].append(
                    {"market_date": d, "d": _mean(c["RICH"]) - _mean(c["CHEAP"])}
                )
        # pass 3: score the differential series per asset_class.
        for asset_class, obs in obs_by_ac.items():
            s = walkforward(
                obs,
                min_n=min_n,
                threshold=DIRECTIONAL_THRESHOLD,
                holdout_threshold=DIRECTIONAL_HOLDOUT,
                value_key="d",
                positive_only=False,
            )
            gates = s["survives_walkforward"] and s["survives_window_gate"]
            mean_d = s["mean"]
            if not gates or mean_d is None:
                verdict = "NEUTRAL"
            elif mean_d > 0:
                verdict = "BULLISH_TILT"
            else:
                verdict = "BEARISH_TILT"
            repo.upsert_vrp_directional_verdict(
                asset_class=asset_class,
                horizon=h,
                verdict=verdict,
                mean_differential=mean_d,
                mean_holdout=s["mean_holdout"],
                mean_rich_return=_mean(rich_all[asset_class]),
                mean_cheap_return=_mean(cheap_all[asset_class]),
                n=s["n"],
                n_holdout=s["n_holdout"],
                survives_walkforward=s["survives_walkforward"],
                survives_window_gate=s["survives_window_gate"],
                confidence="med" if verdict != "NEUTRAL" else None,
                as_of=today,
            )
            written += 1
    repo.conn.commit()
    return {"buckets_written": written}


def _load_dvrp_series(repo: Repository, ticker: str) -> list[dict]:
    sql = (
        "SELECT market_date, vrp, vrp_z_20 "
        f"FROM {repo._schema}.vrp_daily WHERE ticker = %s ORDER BY market_date ASC"
    )
    with repo.conn.cursor() as cur:
        cur.execute(sql, (ticker.upper(),))
        cols = [d.name for d in cur.description or []]
        return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]


def _dvrp_verdict(dev: str, mean: float | None, gates: bool) -> str:
    """RICH should revert DOWN (mean ΔVRP < 0); CHEAP should revert UP (> 0)."""
    if mean is None or not gates:
        return "NEUTRAL"
    rev_sign = -1.0 if dev == "RICH" else (1.0 if dev == "CHEAP" else 0.0)
    if rev_sign == 0.0:
        return "NEUTRAL"  # NORMAL bucket has no reversion hypothesis
    return "REVERTS" if mean * rev_sign > 0 else "PERSISTS"


def run_vrp_dvrp_reversion(
    *,
    repo: Repository,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    min_n: int = MIN_N,
) -> dict[str, Any]:
    """Item 5b. Forward ΔVRP = vrp(t+h)-vrp(t) per (asset_class, deviation_class,
    horizon). Full-rewrite vrp_dvrp_reversion."""
    today = _date.today()
    repo.clear_vrp_dvrp_reversion()
    written = 0
    for h in horizons:
        by_bucket: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for ticker in repo.fetch_distinct_vrp_tickers():
            ordered = _load_dvrp_series(repo, ticker)
            if not ordered:
                continue
            asset_class = _ac(repo, ticker)
            for i, r in enumerate(ordered):
                z = r["vrp_z_20"]
                if z is None:
                    continue
                dev = _deviation_class(float(z))
                if dev is None:
                    continue
                j = i + h
                if j >= len(ordered):
                    continue
                v0, v1 = r["vrp"], ordered[j]["vrp"]
                if v0 is None or v1 is None:  # Pass-3 null guard
                    continue
                by_bucket[(asset_class, dev)].append(
                    {"market_date": r["market_date"], "dvrp": float(v1) - float(v0)}
                )
        for (asset_class, dev), obs in by_bucket.items():
            s = walkforward(
                obs,
                min_n=min_n,
                threshold=DVRP_THRESHOLD,
                holdout_threshold=DVRP_HOLDOUT,
                value_key="dvrp",
                positive_only=False,
            )
            gates = s["survives_walkforward"] and s["survives_window_gate"]
            verdict = _dvrp_verdict(dev, s["mean"], gates)
            repo.upsert_vrp_dvrp_reversion(
                asset_class=asset_class,
                deviation_class=dev,
                horizon=h,
                verdict=verdict,
                mean_fwd_dvrp=s["mean"],
                mean_holdout=s["mean_holdout"],
                n=s["n"],
                n_holdout=s["n_holdout"],
                survives_walkforward=s["survives_walkforward"],
                survives_window_gate=s["survives_window_gate"],
                confidence="med" if verdict in ("REVERTS", "PERSISTS") else None,
                as_of=today,
            )
            written += 1
    repo.conn.commit()
    return {"buckets_written": written}
