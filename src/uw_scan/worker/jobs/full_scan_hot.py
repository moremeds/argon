"""Hot-subset full_scan: tight-freshness intraday refresh of UI-flagged tickers.

Reuses ``full_scan_once`` over just the ``hot`` watchlist tickers with a short
``stale_after`` so every fire does real work. Lives in the live budget pool; the
scheduler caps it via ``max_tickers`` from the governor so flagging more hot
names than the budget allows degrades gracefully (overflow waits).
"""

from __future__ import annotations

import logging
from datetime import timedelta

from uw_scan.sources.ohlc import OhlcProvider
from uw_scan.worker.jobs.full_scan import full_scan_once

logger = logging.getLogger(__name__)


def full_scan_hot_once(
    repo,
    uw_client,
    ohlc_provider: OhlcProvider,
    *,
    stale_minutes: int,
    preserve_spot: bool = False,
    max_tickers: int | None = None,
) -> int:
    hot = set(repo.list_hot_tickers())
    if not hot:
        logger.debug("full_scan_hot: no hot tickers flagged")
        return 0
    if max_tickers == 0:
        logger.info("full_scan_hot: live budget exhausted; skipping this pass")
        return 0
    n = full_scan_once(
        repo,
        uw_client,
        ohlc_provider,
        stale_after=timedelta(minutes=stale_minutes),
        ticker_filter=lambda t: t in hot,
        preserve_spot=preserve_spot,
        max_tickers=max_tickers,
    )
    logger.info("full_scan_hot refreshed %d/%d hot tickers", n, len(hot))
    return n
