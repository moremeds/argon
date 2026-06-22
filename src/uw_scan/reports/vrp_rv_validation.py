"""Item 1 diagnostic: is the trailing-21d RV approximation loose?

For each (ticker, horizon) pair the v1 APPROXIMATION (vrp_daily.rv read `horizon`
trading days forward, positional) against the EXACT corp-action-adjusted realized
vol over [t, t+horizon] from the price series, and persist the deviation
distribution + correlation to vrp_rv_validation. A large mean_abs_dev / low corr
says the shortcut is loose and the harvest should trust the exact RV (it now
does — see vrp_markout.run_vrp_markout).

Design: docs/superpowers/plans/2026-06-22-vrp-research-expansion.md
"""

from __future__ import annotations

import logging
import math
from datetime import date as _date
from typing import Any

from uw_scan.reports.vrp_markout import _load_vrp_series
from uw_scan.reports.vrp_markout_core import (
    apply_split_adjustment,
    forward_realized_vol,
)
from uw_scan.storage.repository import Repository

log = logging.getLogger(__name__)

DEFAULT_HORIZONS = (5, 20, 60)


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = q * (len(ordered) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return ordered[lo]
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 2:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=False))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return None
    return sxy / math.sqrt(sxx * syy)


def run_vrp_rv_validation(
    *, repo: Repository, horizons: tuple[int, ...] = DEFAULT_HORIZONS
) -> dict[str, Any]:
    """Full-rewrite vrp_rv_validation. Pure compute over vrp_daily + price series;
    idempotent. Skips a ticker with no price coverage (cannot compute exact RV)."""
    today = _date.today()
    repo.clear_vrp_rv_validation()
    written = 0
    for ticker in repo.fetch_distinct_vrp_tickers():
        vrp_rows = _load_vrp_series(repo, ticker)
        if len(vrp_rows) < 2:
            continue
        ordered = sorted(vrp_rows, key=lambda r: r["market_date"])
        adj = apply_split_adjustment(
            repo.fetch_price_series(ticker), repo.fetch_corporate_actions(ticker)
        )
        if not adj:
            continue
        pidx = {d: k for k, (d, _v) in enumerate(adj)}
        for h in horizons:
            approx_list: list[float] = []
            exact_list: list[float] = []
            for i, r in enumerate(ordered):
                j = i + h
                if j >= len(ordered) or ordered[j]["rv"] is None:
                    continue
                pi = pidx.get(r["market_date"])
                if pi is None:
                    continue
                exact = forward_realized_vol(adj, pi, h)
                if exact is None:
                    continue
                approx_list.append(float(ordered[j]["rv"]))
                exact_list.append(exact)
            n = len(approx_list)
            if n == 0:
                continue
            devs = [a - e for a, e in zip(approx_list, exact_list, strict=False)]
            repo.upsert_vrp_rv_validation(
                ticker=ticker,
                horizon=h,
                n=n,
                mean_abs_dev=sum(abs(d) for d in devs) / n,
                mean_signed_dev=sum(devs) / n,
                p95_abs_dev=_percentile([abs(d) for d in devs], 0.95),
                corr=_pearson(approx_list, exact_list),
                as_of=today,
            )
            written += 1
    repo.conn.commit()
    return {"rows_written": written}
