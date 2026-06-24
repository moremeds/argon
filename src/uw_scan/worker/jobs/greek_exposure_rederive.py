"""Nightly DB->DB re-derive of single-name greek_exposure_daily from the
per-strike exposures_by_expiry_strike table (#179). Zero UW calls.

For each active watchlist ticker: sum the canonical run's per-strike GEX/DEX
per market_date and upsert into greek_exposure_daily (net_gex/net_dex are
generated columns). For the index tickers that ALSO have a UW-fed stored
series (gex_scan_tickers, default SPX/SPY/TLT), compare re-derived vs stored
net_gex and persist the diff to greek_rederive_validation; WARN on material
divergence so a basis mismatch is never shipped silently.
"""

from __future__ import annotations

import logging
from datetime import date

from uw_scan.config import Settings
from uw_scan.storage.greek_exposure_repository import GreekExposureDailyRepository
from uw_scan.storage.repository import Repository

logger = logging.getLogger(__name__)

# ponytail: 1% net_gex divergence is the WARN line; tighten if validation
# shows the per-strike sum tracks UW's aggregate more closely than that.
VALIDATION_WARN_PCT = 0.01


def greek_exposure_rederive(
    *,
    repo: Repository,
    settings: Settings,
    run_date: date,
    since: date | None = None,
    validate_tickers: list[str] | None = None,
) -> dict[str, int]:
    g = GreekExposureDailyRepository(repo.conn, schema=settings.db_schema)
    validate = {t.upper() for t in (validate_tickers or settings.gex_scan_tickers)}

    tickers_done = 0
    rows_written = 0
    validated = 0
    warns = 0
    validate_had_rows = False  # did any index ticker even have per-strike rows?

    for card in repo.list_watchlist_cards():
        ticker = card.ticker
        rows = g.select_rederived_rows(ticker=ticker, since=since)
        if not rows:
            continue
        # Index tickers already have an authoritative UW-fed series; do NOT
        # overwrite it with the per-strike proxy. Re-derive single names only,
        # but still validate the indices' proxy against their stored truth.
        if ticker.upper() not in validate:
            g.upsert_rows(
                ticker,
                [{**r, "payload": {"source": "rederive_from_strikes"}} for r in rows],
            )
            rows_written += len(rows)
        else:
            validate_had_rows = True
            diffs = g.compare_to_stored(rows)
            validated += g.insert_validation_rows(run_date, diffs)
            for d in diffs:
                if d["pct_diff"] is not None and d["pct_diff"] > VALIDATION_WARN_PCT:
                    warns += 1
                    logger.warning(
                        "greek_rederive validation: %s %s rederived=%.2f stored=%.2f "
                        "pct=%.4f exceeds %.4f — per-strike basis differs from UW aggregate",
                        d["ticker"],
                        d["trade_date"],
                        d["rederived_net_gex"],
                        d["stored_net_gex"],
                        d["pct_diff"],
                        VALIDATION_WARN_PCT,
                    )

        tickers_done += 1

    # The basis check is load-bearing (Decision-1): if the index tickers had
    # per-strike rows but produced ZERO comparable dates (no overlapping stored
    # rows), validation silently did nothing. Surface that as a WARN so "no
    # warnings" never gets misread as "basis confirmed".
    if validate_had_rows and validated == 0:
        logger.warning(
            "greek_rederive: validation produced 0 comparable rows for %s — "
            "basis check did NOT run (no overlapping per-strike + stored dates)",
            sorted(validate),
        )

    summary = {
        "tickers": tickers_done,
        "rows": rows_written,
        "validated": validated,
        "warn": warns,
    }
    logger.info(
        "greek_exposure_rederive complete tickers=%d rows=%d validated=%d warn=%d",
        summary["tickers"],
        summary["rows"],
        summary["validated"],
        summary["warn"],
    )
    return summary
