"""Full scan job: per-ticker run_single_stock + watchlist_card derive + upsert."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from uw_scan.cards.derive import compute_watchlist_card_row
from uw_scan.pipeline import run_single_stock
from uw_scan.sources.ohlc import OhlcProvider

logger = logging.getLogger(__name__)
DEFAULT_STALE_AFTER = timedelta(hours=8)


def _is_missing_or_stale(
    scanned_at: datetime | None, *, now: datetime, stale_after: timedelta
) -> bool:
    if scanned_at is None:
        return True
    scanned = scanned_at
    if scanned.tzinfo is None:
        scanned = scanned.replace(tzinfo=timezone.utc)
    current = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc) - scanned.astimezone(
        timezone.utc
    ) > stale_after


def full_scan_once(
    repo,
    uw_client,
    ohlc_provider: OhlcProvider,
    *,
    now: datetime | None = None,
    stale_after: timedelta = DEFAULT_STALE_AFTER,
    ticker_filter: Callable[[str], bool] | None = None,
) -> int:
    """Run UW deep scans only for active tickers missing data or older than max age."""
    _ = ohlc_provider  # currently OHLC is pulled separately; reserved for future
    current = now or datetime.now(timezone.utc)
    completed = 0
    for w in repo.list_watchlist_cards():
        if ticker_filter is not None and not ticker_filter(w.ticker):
            logger.debug("full_scan skipped %s outside this worker shard", w.ticker)
            continue
        if not _is_missing_or_stale(
            w.scanned_at, now=current, stale_after=stale_after
        ):
            logger.debug("full_scan skipped fresh persisted data for %s", w.ticker)
            continue
        try:
            report = run_single_stock(w.ticker, uw_client, repo)
            history = repo.list_daily_ohlc(w.ticker, limit=40)
            intraday = repo.get_intraday_quote(w.ticker)
            prior_pcr = repo.get_pcr_history_30d_ago(
                w.ticker, today=report.generated_at.date()
            )
            card_row = compute_watchlist_card_row(report, history, intraday, prior_pcr)
            repo.upsert_watchlist_card(**card_row)
            completed += 1
        except Exception as exc:  # noqa: BLE001
            logger.exception("full_scan failed for %s: %s", w.ticker, repr(exc))
    return completed
