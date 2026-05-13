"""Full scan job: per-ticker run_single_stock + watchlist_card derive + upsert."""

from __future__ import annotations

import logging

from uw_scan.cards.derive import compute_watchlist_card_row
from uw_scan.pipeline import run_single_stock
from uw_scan.sources.ohlc import OhlcProvider

logger = logging.getLogger(__name__)


def full_scan_once(repo, uw_client, ohlc_provider: OhlcProvider) -> int:
    """Run the UW deep-scan for every active watchlist ticker and rebuild cards."""
    _ = ohlc_provider  # currently OHLC is pulled separately; reserved for future
    completed = 0
    for w in repo.list_active_watchlist():
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
