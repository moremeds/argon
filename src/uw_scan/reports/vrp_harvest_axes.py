"""VRP harvest axes A (sector, item 2) + B (multi-horizon, item 4).

Both reuse the corrected harvest observation builder (exact corp-action-adjusted
forward RV + buffered earnings exclusion) from vrp_markout, parameterized by
horizon and bucket key:

- Axis A: single-name harvest re-cut by sector — WHERE is single-name vol
  (un)sellable? Bucket (sector, deviation_class).
- Axis B: harvest at horizons {5,20,60} — the premium decay curve. Bucket
  (asset_class, deviation_class, horizon).

Both are FULL-REWRITE per run. Same OOS thresholds as the headline harvest.

Design: docs/superpowers/plans/2026-06-22-vrp-research-expansion.md
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date as _date
from typing import Any, Callable

from uw_scan.cards.skew_first_principles import asset_class_baseline
from uw_scan.reports.vrp_markout import (
    _adjusted_forward_rv_fn,
    _harvest_obs,
    _load_vrp_series,
)
from uw_scan.reports.vrp_markout_core import MIN_N, apply_split_adjustment, walkforward
from uw_scan.storage.repository import Repository

log = logging.getLogger(__name__)

HARVEST_THRESHOLD = 0.02
HOLDOUT_THRESHOLD = 0.01
DEFAULT_HORIZONS = (5, 20, 60)


def _collect(
    repo: Repository,
    *,
    horizon: int,
    key_fn: Callable[[str, str, str | None], str | None],
) -> dict[tuple[str, str], list[dict]]:
    """Build {(base_key, deviation_class): [obs]} at a given horizon. key_fn
    maps (ticker, asset_class, sector) → base bucket key, or None to drop the
    ticker. Honors the single_name no-earnings skip-guard and uses exact
    corp-action-adjusted forward RV; tickers with no price coverage are skipped."""
    by_bucket: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for ticker in repo.fetch_distinct_vrp_tickers():
        rows = _load_vrp_series(repo, ticker)
        if not rows:
            continue
        sector = repo.fetch_watchlist_sector(ticker)
        asset_class = asset_class_baseline(ticker, sector=sector)["asset_class"]
        base_key = key_fn(ticker, asset_class, sector)
        if base_key is None:
            continue
        if asset_class == "single_name" and not repo.fetch_historical_earnings_dates(
            ticker
        ):
            continue  # cannot honor the earnings exclusion → exclude (false-SELLABLE guard)
        adj = apply_split_adjustment(
            repo.fetch_price_series(ticker), repo.fetch_corporate_actions(ticker)
        )
        if not adj:
            continue
        forward_fn = _adjusted_forward_rv_fn(adj, horizon=horizon)
        events = repo.fetch_earnings_events(ticker)
        for o in _harvest_obs(rows, events=events, forward_fn=forward_fn):
            by_bucket[(base_key, o["deviation_class"])].append(o)
    return by_bucket


def _score_buckets(
    by_bucket: dict[tuple[str, str], list[dict]], min_n: int
) -> tuple[dict[tuple[str, str], dict], dict[str, float | None]]:
    scored = {
        key: walkforward(
            obs,
            min_n=min_n,
            threshold=HARVEST_THRESHOLD,
            holdout_threshold=HOLDOUT_THRESHOLD,
            value_key="realized_vrp",
            positive_only=True,
        )
        for key, obs in by_bucket.items()
    }
    spread: dict[str, float | None] = {}
    for base in {k[0] for k in by_bucket}:
        rich = scored.get((base, "RICH"), {}).get("mean")
        cheap = scored.get((base, "CHEAP"), {}).get("mean")
        spread[base] = rich - cheap if rich is not None and cheap is not None else None
    return scored, spread


def _verdict(s: dict) -> str:
    return (
        "HARVEST_SELLABLE"
        if (s["survives_walkforward"] and s["survives_window_gate"])
        else "NONE"
    )


def run_vrp_harvest_by_sector(
    *, repo: Repository, horizon: int = 20, min_n: int = MIN_N
) -> dict[str, Any]:
    """Item 2: single-name harvest re-bucketed by sector. Full-rewrite."""
    today = _date.today()
    by_bucket = _collect(
        repo,
        horizon=horizon,
        key_fn=lambda _t, ac, sec: (sec or "unknown") if ac == "single_name" else None,
    )
    scored, spread = _score_buckets(by_bucket, min_n)
    repo.clear_vrp_harvest_by_sector()
    written = 0
    for (sector, dev), s in scored.items():
        verdict = _verdict(s)
        repo.upsert_vrp_harvest_by_sector(
            sector=sector,
            deviation_class=dev,
            verdict=verdict,
            mean_realized_vrp=s["mean"],
            mean_holdout=s["mean_holdout"],
            rich_cheap_spread=spread.get(sector),
            n=s["n"],
            n_holdout=s["n_holdout"],
            survives_walkforward=s["survives_walkforward"],
            survives_window_gate=s["survives_window_gate"],
            confidence="med" if verdict == "HARVEST_SELLABLE" else None,
            as_of=today,
        )
        written += 1
    repo.conn.commit()
    return {"buckets_written": written}


def run_vrp_harvest_multihorizon(
    *,
    repo: Repository,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    min_n: int = MIN_N,
) -> dict[str, Any]:
    """Item 4: harvest at each horizon (the decay curve). Full-rewrite."""
    today = _date.today()
    repo.clear_vrp_harvest_multihorizon()
    written = 0
    for h in horizons:
        by_bucket = _collect(repo, horizon=h, key_fn=lambda _t, ac, _sec: ac)
        scored, spread = _score_buckets(by_bucket, min_n)
        for (asset_class, dev), s in scored.items():
            verdict = _verdict(s)
            repo.upsert_vrp_harvest_multihorizon(
                asset_class=asset_class,
                deviation_class=dev,
                horizon=h,
                verdict=verdict,
                mean_realized_vrp=s["mean"],
                mean_holdout=s["mean_holdout"],
                rich_cheap_spread=spread.get(asset_class),
                n=s["n"],
                n_holdout=s["n_holdout"],
                survives_walkforward=s["survives_walkforward"],
                survives_window_gate=s["survives_window_gate"],
                confidence="med" if verdict == "HARVEST_SELLABLE" else None,
                as_of=today,
            )
            written += 1
    repo.conn.commit()
    return {"buckets_written": written}
