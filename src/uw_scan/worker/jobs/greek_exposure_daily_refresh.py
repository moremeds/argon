"""Nightly single-name greek_exposure_daily refresh from UW's aggregate
/greek-exposure history (#179).

The index tickers (gex_scan_tickers, default SPX/SPY/TLT) already get their
authoritative daily GEX/DEX from the regime GEX scan. Single names had no
recurring writer and froze at 2026-05-20. An earlier attempt summed the
per-strike exposures_by_expiry_strike table DB->DB, but validation showed that
partial-chain sum is 20-134% off UW's full-chain aggregate — a different,
untrustworthy basis. So we fetch UW's aggregate series directly (one call per
ticker, ~250 trailing days), giving single names the SAME basis as the indices.

One UW call per single-name ticker; single-flight via pg_try_advisory_lock;
per-ticker transactions commit on success and roll back on failure.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from uw_scan.api.client import UwClient
from uw_scan.config import Settings
from uw_scan.scanners.gex import fetch_aggregate_gex
from uw_scan.storage.greek_exposure_repository import GreekExposureDailyRepository
from uw_scan.storage.repository import Repository

logger = logging.getLogger(__name__)

GREEK_DAILY_REFRESH_LOCK = 91503  # mnemonic: migration 049 + slot 03


def greek_exposure_daily_refresh(
    *,
    repo: Repository,
    client: UwClient,
    settings: Settings,
    ticker_filter: Callable[[str], bool] | None = None,
    lock_key: int = GREEK_DAILY_REFRESH_LOCK,
) -> dict[str, int]:
    """Refresh single-name greek_exposure_daily from UW's aggregate history.

    Returns a summary dict: ``{"tickers", "rows", "skipped_index", "errors"}``.
    """
    if not repo.try_advisory_lock(lock_key):
        logger.info("greek_daily_refresh: lock held; skipping this tick")
        return {"tickers": 0, "rows": 0, "skipped_index": 0, "errors": 0}

    g = GreekExposureDailyRepository(repo.conn, schema=settings.db_schema)
    # Indices already refreshed by the regime GEX scan — don't double-fetch.
    index_set = {t.upper() for t in settings.gex_scan_tickers}

    tickers_done = 0
    rows_written = 0
    skipped_index = 0
    errors = 0

    try:
        for card in repo.list_watchlist_cards():
            ticker = card.ticker.upper()
            if ticker in index_set:
                skipped_index += 1
                continue
            if ticker_filter is not None and not ticker_filter(ticker):
                continue

            run_id = repo.insert_scan_run(ticker, notes="greek_exposure_daily_refresh")
            try:
                aggregate_rows = fetch_aggregate_gex(client, repo, run_id, ticker)
                n = g.upsert_rows(
                    ticker,
                    [
                        {
                            "trade_date": h["date"],
                            "call_gex": h["call_gex"],
                            "put_gex": h["put_gex"],
                            "call_delta": h["call_delta"],
                            "put_delta": h["put_delta"],
                            # trade_date lives in its own column; drop it from
                            # the JSONB payload (keeps the same shape gex.run
                            # writes for the index tickers).
                            "payload": {k: v for k, v in h.items() if k != "date"},
                        }
                        for h in aggregate_rows
                    ],
                )
                repo.finish_scan_run(run_id, status="ok")
                repo.conn.commit()
                rows_written += n
                tickers_done += 1
            except Exception as exc:  # noqa: BLE001
                repo.conn.rollback()
                errors += 1
                logger.warning("greek_daily_refresh: %s failed: %s", ticker, repr(exc))
    finally:
        repo.release_advisory_lock(lock_key)

    summary = {
        "tickers": tickers_done,
        "rows": rows_written,
        "skipped_index": skipped_index,
        "errors": errors,
    }
    logger.info(
        "greek_exposure_daily_refresh complete tickers=%d rows=%d skipped_index=%d errors=%d",
        summary["tickers"],
        summary["rows"],
        summary["skipped_index"],
        summary["errors"],
    )
    return summary
