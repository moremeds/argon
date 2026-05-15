"""Spot-refresh job: pull intraday quote from massive.com and refresh
spot-anchored card fields (spot, spot_source, spot_quoted_at, 1d/1w/30d
returns).

Other GEX-derived spot fields (gex_per_1pct_move, gex_flip_distance)
naturally drift between full-scan cycles because net_gex isn't stored on
the card row. The next full scan resets them — acceptable per spec.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date

from uw_scan.cards.returns import compute_returns
from uw_scan.sources.ohlc import OhlcProvider

logger = logging.getLogger(__name__)


def spot_refresh_once(
    repo,
    provider: OhlcProvider,
    *,
    market_date: date | None = None,
    ticker_filter: Callable[[str], bool] | None = None,
) -> int:
    """One pass over the active watchlist. Returns the number of cards updated."""
    updated = 0
    for w in repo.list_active_watchlist():
        if ticker_filter is not None and not ticker_filter(w.ticker):
            logger.debug("spot_refresh skipped %s outside this worker shard", w.ticker)
            continue
        try:
            quote = provider.fetch_intraday_quote(w.ticker, market_date=market_date)
            if quote is None:
                continue
            repo.upsert_intraday_quote(w.ticker, quote.price, quote.quoted_at)
            existing = repo.get_watchlist_card(w.ticker)
            if existing is None:
                # No full scan has produced a card yet — skip partial write.
                continue
            history = repo.list_daily_ohlc(w.ticker, limit=40)
            returns = compute_returns(history, quote.price)
            repo.upsert_watchlist_card(
                ticker=w.ticker,
                run_id=existing.run_id,
                scanned_at=existing.scanned_at,
                spot=quote.price,
                spot_quoted_at=quote.quoted_at,
                spot_source="massive.com_intraday",
                ret_1d=returns.ret_1d,
                ret_1w=returns.ret_1w,
                ret_30d=returns.ret_30d,
            )
            updated += 1
        except Exception as exc:  # noqa: BLE001
            logger.exception("spot_refresh failed for %s: %s", w.ticker, repr(exc))
    return updated
