"""IB-vs-UW IV canary.

For each watchlist ticker, compare IB's modelGreeks impliedVol (via xenon's read-only
query API) against UW's captured IV at the ATM call strike for the front 2 expiries.
Persists every comparison to iv_source_validation and WARNs when the watchlist-wide
median abs diff exceeds the configured threshold — an early signal that the UW-sourced
surface can't be trusted. Targeted (per-contract) calls only; never bulk.
"""

from __future__ import annotations

import logging
from datetime import date as _date
from decimal import Decimal
from statistics import median as _median

from uw_scan.sources.xenon_query import fetch_ib_option_iv
from uw_scan.storage.repository import Repository

log = logging.getLogger(__name__)

_FRONT_EXPIRIES = 2


def _front_expiries(repo: Repository, ticker: str, market_date: _date) -> list[_date]:
    with repo.conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT expiry FROM uw_scan.option_surface_grid_daily "
            "WHERE ticker=%s AND market_date=%s ORDER BY expiry ASC LIMIT %s",
            (ticker.upper(), market_date, _FRONT_EXPIRIES),
        )
        return [r[0] for r in cur.fetchall()]


def option_surface_iv_canary(
    *, repo: Repository, settings, today: _date | None = None
) -> Decimal | None:
    """Diff IB vs UW IV at the ATM call strike for the front 2 expiries, per ticker.
    Returns the watchlist-wide median abs_diff (None if no comparisons)."""
    if today is None:
        today = _date.today()
    api_key = (
        settings.xenon_query_api_key.get_secret_value()
        if settings.xenon_query_api_key is not None
        else None
    )
    diffs: list[Decimal] = []
    for card in repo.list_watchlist_cards():
        ticker, spot = card.ticker, card.spot
        if spot is None:
            continue
        for expiry in _front_expiries(repo, ticker, today):
            atm = repo.fetch_option_surface_atm_strike(ticker, today, expiry, spot)
            if atm is None:
                continue
            ib_iv = fetch_ib_option_iv(
                base_url=settings.xenon_query_api_url,
                api_key=api_key,
                symbol=ticker,
                expiry=expiry.strftime("%Y%m%d"),
                strike=float(atm["strike"]),
                right="C",
            )
            uw_iv = atm.get("call_iv")
            repo.upsert_iv_source_validation(
                ticker, today, expiry, atm["strike"], "C", uw_iv, ib_iv
            )
            if uw_iv is not None and ib_iv is not None:
                diffs.append(abs(uw_iv - ib_iv))
        repo.conn.commit()

    if not diffs:
        log.info("option_surface_iv_canary: no comparisons available")
        return None
    med = _median(diffs)
    threshold = Decimal(str(settings.option_surface_iv_canary_warn_threshold))
    if med > threshold:
        log.warning(
            "option_surface_iv_canary: median IB-vs-UW IV diff %.4f exceeds %.4f over %d contracts",
            med,
            threshold,
            len(diffs),
        )
    else:
        log.info(
            "option_surface_iv_canary: median IB-vs-UW IV diff %.4f (%d contracts)",
            med,
            len(diffs),
        )
    return med
