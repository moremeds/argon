"""Today's per-ticker iron-condor candidates: RICH × SELLABLE-sector × earnings-
clear. Flat-vol modeled credit. Full-rewrite for as_of; commits per ticker (the
scheduler _repo() does not commit on close — see plan §Global Constraints).

Design: docs/superpowers/plans/2026-06-22-vrp-tradable-condor-backtest.md
"""

from __future__ import annotations

import logging
from datetime import date as _date
from datetime import timedelta
from typing import Any

from uw_scan.cards.skew_first_principles import asset_class_baseline
from uw_scan.reports.vrp_markout import RICH_Z, _events_overlap, _load_vrp_series
from uw_scan.reports.vrp_markout_core import apply_split_adjustment
from uw_scan.reports.vrp_structure import CostModel, build_iron_condor

log = logging.getLogger(__name__)


def _sellable_sectors(repo) -> set[str]:
    return {
        r["sector"]
        for r in repo.fetch_vrp_harvest_by_sector()
        if r["deviation_class"] == "RICH" and r["verdict"] == "HARVEST_SELLABLE"
    }


def run_vrp_candidates(*, repo, settings, as_of: _date | None = None) -> dict[str, Any]:
    today = as_of or _date.today()
    hd = settings.vrp_hold_days
    t_years = hd / 252.0
    sellable = _sellable_sectors(repo)
    cost = CostModel(
        settings.vrp_cost_per_contract,
        settings.vrp_slippage_frac,
        settings.vrp_slippage_min,
        round_trip=settings.vrp_cost_round_trip,
    )
    repo.clear_vrp_candidates(today)
    repo.conn.commit()  # durable even if zero tickers qualify (per-ticker commits
    #                     would otherwise leave the DELETE uncommitted → rolled back
    #                     on close → stale candidates survive; idempotency bug)
    written = 0
    for ticker in repo.fetch_distinct_vrp_tickers():
        try:
            rows = _load_vrp_series(repo, ticker)
            # ISSUE-7: align the signal to as_of (no future leak on backfill runs)
            eligible = [r for r in rows if r["market_date"] <= today]
            if not eligible:
                continue
            latest = eligible[-1]
            z, iv = latest["vrp_z_20"], latest["iv"]
            if z is None or iv is None or float(iv) <= 0 or float(z) < RICH_Z:
                continue  # iv<=0 → degenerate condor; skip
            sector = repo.fetch_watchlist_sector(ticker)
            ac = asset_class_baseline(ticker, sector=sector)["asset_class"]
            if ac != "single_name":  # v1: single-name-by-sector edge only
                continue
            if (sector or "unknown") not in sellable:
                continue
            # ISSUE-6: can't honor the earnings exclusion without a calendar → don't emit
            if not repo.fetch_historical_earnings_dates(ticker):
                continue
            # spot = adjusted close on the SIGNAL date (entry), not the series tail
            adj = apply_split_adjustment(
                repo.fetch_price_series(ticker), repo.fetch_corporate_actions(ticker)
            )
            pmap = {d: v for d, v in adj}
            entry = latest["market_date"]
            spot = pmap.get(entry)
            if spot is None or spot <= 0:
                continue
            window_end = entry + timedelta(days=int(round(hd * 7 / 5)))  # ~cal days
            events = repo.fetch_earnings_events(ticker)
            if _events_overlap(entry, window_end, events):
                continue  # earnings inside the forward window → stand aside
            ic = build_iron_condor(
                spot,
                float(iv),
                t_years,
                settings.vrp_risk_free_rate,
                short_delta=settings.vrp_short_delta,
                wing_delta=settings.vrp_wing_delta,
            )
            verdict = (
                "HARVEST_SELLABLE"  # passed the single-name + SELLABLE-sector gate
            )
            repo.upsert_vrp_candidate(
                ticker=ticker,
                as_of=today,
                structure="iron_condor",
                spot=spot,
                iv=float(iv),
                vrp_z=float(z),
                hold_days=hd,
                short_put=ic.short_put,
                long_put=ic.long_put,
                short_call=ic.short_call,
                long_call=ic.long_call,
                entry_credit=ic.credit,
                max_loss=ic.max_loss,
                put_width=ic.put_width,
                call_width=ic.call_width,
                entry_cost=cost.total(ic.leg_premiums, 1),
                bucket_sector=sector,
                bucket_verdict=verdict,
                earnings_clear=True,
                contracts=1,
            )
            repo.conn.commit()
            written += 1
        except Exception as exc:  # noqa: BLE001
            repo.conn.rollback()
            log.exception("vrp_candidates failed for %s: %s", ticker, repr(exc))
    return {"written": written, "as_of": today.isoformat()}
