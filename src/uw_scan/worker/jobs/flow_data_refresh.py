"""Nightly refresh of the Flow tab's data sources.

Pulls ~180-day options-volume timeline + per-(expiry, strike) volume/OI
snapshot for every watchlist ticker.  Single-flight via
``pg_try_advisory_lock`` so overlapping ticks no-op gracefully.

Per-ticker semantics:
- one ``scan_runs`` row per ticker so failures stay visible in the table
  (run is left unfinished if the ticker raises);
- ``DELETE`` + ``INSERT`` for the chain snapshot (shrinking chains must
  not leave stale strikes behind);
- ``commit()`` on success, ``rollback()`` on failure so an aborted
  per-ticker transaction never poisons the next ticker.
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from uw_scan.api.client import UwClient
from uw_scan.cards.option_chain import aggregate_chain_per_strike
from uw_scan.config import Settings
from uw_scan.sources.uw import fetch_option_contracts, fetch_options_volume_daily
from uw_scan.storage.repository import Repository

logger = logging.getLogger(__name__)

FLOW_REFRESH_LOCK = 91501  # mnemonic: migration 015 + slot 01
MAX_PCT_FROM_SPOT = Decimal("0.60")
MAX_DTE_DAYS = 365
OPTIONS_VOLUME_LOOKBACK = 200


def flow_data_refresh(
    *, repo: Repository, client: UwClient, settings: Settings
) -> None:
    """Refresh Flow-tab tables for every watchlist ticker."""

    if not repo.try_advisory_lock(FLOW_REFRESH_LOCK):
        logger.info("flow_data_refresh: lock held; skipping this tick")
        return

    try:
        # ET market date, not host date — host may be HKT/UTC.
        market_date = datetime.now(ZoneInfo(settings.rth_tz)).date()

        cards = repo.list_watchlist_cards()
        for card in cards:
            ticker = card.ticker
            run_id = repo.insert_scan_run(ticker, notes="flow_data_refresh")
            try:
                vol_rows = fetch_options_volume_daily(
                    client, repo, run_id, ticker, limit=OPTIONS_VOLUME_LOOKBACK
                )
                n = repo.upsert_options_volume_daily(ticker, vol_rows)
                logger.info(
                    "flow_data_refresh: %s options_volume_daily rows=%d", ticker, n
                )

                spot = card.spot
                if spot is None or Decimal(str(spot)) <= 0:
                    logger.warning(
                        "flow_data_refresh: %s missing spot, skipping chain", ticker
                    )
                    repo.finish_scan_run(run_id, status="ok")
                    repo.conn.commit()
                    continue

                contracts = fetch_option_contracts(
                    client, repo, run_id, ticker, limit=500
                )
                chain_rows = aggregate_chain_per_strike(
                    contracts,
                    spot=Decimal(str(spot)),
                    max_pct_from_spot=MAX_PCT_FROM_SPOT,
                    max_dte_days=MAX_DTE_DAYS,
                    today=market_date,
                )
                repo.delete_option_chain_per_strike(ticker, market_date)
                m = repo.upsert_option_chain_per_strike(ticker, market_date, chain_rows)
                logger.info(
                    "flow_data_refresh: %s option_chain_per_strike rows=%d",
                    ticker,
                    m,
                )
                repo.finish_scan_run(run_id, status="ok")
                repo.conn.commit()
            except Exception as exc:  # noqa: BLE001
                # Abort the per-ticker transaction so the next ticker is not
                # stuck in an aborted-transaction state. Leave the scan run
                # unfinished so failures are visible in scan_runs.
                repo.conn.rollback()
                logger.exception("flow_data_refresh: %s failed: %r", ticker, exc)
    finally:
        repo.release_advisory_lock(FLOW_REFRESH_LOCK)
