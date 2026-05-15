"""Nightly per-strike + per-expiry snapshot for the Cockpit universe.

For each ticker in ``settings.cockpit_tickers`` (SPX / SPY / QQQ / IWM by
default), this job fetches the inputs the 6-dimension matrix needs and
persists them to existing tables (``greeks_by_expiry_strike``,
``exposures_by_expiry_strike``, ``risk_reversal_skew_history``,
``iv_term_snapshots``, ``interpolated_iv_snapshots``,
``realized_volatility_history``, ``iv_rank_history``), then derives and
persists one ``matrix_state_snapshots`` row per ticker.

Per-ticker error semantics mirror ``flow_data_refresh``:
- One ``scan_runs`` row per ticker so failures stay visible;
- ``commit()`` on success, ``rollback()`` on failure so an aborted
  per-ticker transaction never poisons the next ticker.

Single-flight via ``pg_try_advisory_lock`` (key 92201, mnemonic
"migration 022, slot 01").
"""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import psycopg

from uw_scan.api.client import UwClient
from uw_scan.cards.matrix_state import build_matrix_state
from uw_scan.cards.option_chain import aggregate_chain_per_strike, pick_target_expiries
from uw_scan.config import Settings
from uw_scan.sources.uw import (
    fetch_greek_exposure,
    fetch_greeks,
    fetch_interpolated_iv,
    fetch_iv_rank,
    fetch_option_contracts,
    fetch_realized_volatility,
    fetch_skew,
    fetch_term_structure,
)
from uw_scan.storage.repository import Repository

logger = logging.getLogger(__name__)

COCKPIT_SNAPSHOT_LOCK = 92201
OPTION_CONTRACTS_LIMIT = 500


def cockpit_daily_snapshot(
    *, repo: Repository, client: UwClient, settings: Settings
) -> None:
    """Snapshot greeks/exposures/skew/IV/RV for every Cockpit ticker."""

    if not repo.try_advisory_lock(COCKPIT_SNAPSHOT_LOCK):
        logger.info("cockpit_daily_snapshot: lock held; skipping this tick")
        return

    try:
        market_date = datetime.now(ZoneInfo(settings.rth_tz)).date()
        tickers = list(settings.cockpit_tickers)
        target_dtes = list(settings.cockpit_target_dtes)

        for ticker in tickers:
            run_id = repo.insert_scan_run(ticker, notes="cockpit_daily_snapshot")
            try:
                _snapshot_ticker(
                    repo=repo,
                    client=client,
                    run_id=run_id,
                    ticker=ticker,
                    market_date=market_date,
                    target_dtes=target_dtes,
                    oi_band_pct=settings.cockpit_oi_band_pct,
                    oi_max_dte=settings.cockpit_oi_max_dte,
                )
                repo.finish_scan_run(run_id, status="ok")
                repo.conn.commit()
                try:
                    with psycopg.connect(settings.db_dsn()) as deriver_conn:
                        deriver_repo = Repository(
                            deriver_conn, schema=settings.db_schema
                        )
                        state = build_matrix_state(
                            deriver_repo, ticker=ticker, market_date=market_date
                        )
                        deriver_repo.upsert_matrix_state_snapshot(state)
                        deriver_repo.persist_vrp_30d_settlements(
                            ticker=ticker, market_date=market_date
                        )
                        deriver_repo.persist_cockpit_dealer_signals(
                            ticker=ticker, market_date=market_date
                        )
                        deriver_conn.commit()
                except Exception as deriver_exc:  # noqa: BLE001
                    logger.exception(
                        "cockpit_daily_snapshot: %s deriver failed: %r",
                        ticker,
                        deriver_exc,
                        extra={"deriver_failed": True},
                    )
            except Exception as exc:  # noqa: BLE001
                repo.conn.rollback()
                logger.exception("cockpit_daily_snapshot: %s failed: %r", ticker, exc)
    finally:
        repo.release_advisory_lock(COCKPIT_SNAPSHOT_LOCK)


def _snapshot_ticker(
    *,
    repo: Repository,
    client: UwClient,
    run_id: int,
    ticker: str,
    market_date,
    target_dtes: list[int],
    oi_band_pct,
    oi_max_dte: int,
) -> None:
    """Fetch + persist the full Cockpit input set for a single ticker."""

    # 1. Single-call series — daily-resolution IV/RV/Term/IVRank.
    rv_rows = fetch_realized_volatility(client, repo, run_id, ticker)
    n_rv = repo.upsert_realized_vol_rows(ticker, rv_rows)

    iv_rank_rows = fetch_iv_rank(client, repo, run_id, ticker)
    n_ivr = repo.upsert_iv_rank_rows(ticker, iv_rank_rows)

    term_rows = fetch_term_structure(client, repo, run_id, ticker)
    n_term = repo.insert_iv_term_rows(run_id, term_rows)

    interp_rows = fetch_interpolated_iv(client, repo, run_id, ticker)
    n_iv = repo.insert_interpolated_iv_rows(run_id, ticker, interp_rows)

    logger.info(
        "cockpit_daily_snapshot: %s series rv=%d ivrank=%d term=%d interp=%d",
        ticker,
        n_rv,
        n_ivr,
        n_term,
        n_iv,
    )

    # 2. Per-expiry detail — pick expiries nearest each target DTE.
    contracts = fetch_option_contracts(
        client, repo, run_id, ticker, limit=OPTION_CONTRACTS_LIMIT
    )
    _persist_option_chain_per_strike(
        repo=repo,
        ticker=ticker,
        market_date=market_date,
        contracts=contracts,
        oi_band_pct=oi_band_pct,
        oi_max_dte=oi_max_dte,
    )
    expiries = pick_target_expiries(
        contracts, target_dtes=target_dtes, today=market_date
    )
    if not expiries:
        logger.warning(
            "cockpit_daily_snapshot: %s no expiries found, skipping greeks",
            ticker,
        )
        return

    for expiry in expiries:
        expiry_iso = expiry.isoformat()

        greeks_rows = fetch_greeks(client, repo, run_id, ticker, expiry_iso)
        n_g = repo.insert_greeks_rows(run_id, ticker, greeks_rows)

        exposure_rows = fetch_greek_exposure(client, repo, run_id, ticker, expiry_iso)
        n_e = repo.insert_greek_exposure_rows(run_id, ticker, exposure_rows)

        skew_rows = fetch_skew(client, repo, run_id, ticker, expiry_iso, delta=25)
        n_s = repo.upsert_skew_rows(ticker, skew_rows)

        logger.info(
            "cockpit_daily_snapshot: %s exp=%s greeks=%d exposures=%d skew=%d",
            ticker,
            expiry_iso,
            n_g,
            n_e,
            n_s,
        )


def _persist_option_chain_per_strike(
    *,
    repo: Repository,
    ticker: str,
    market_date,
    contracts,
    oi_band_pct,
    oi_max_dte: int,
) -> None:
    quote = repo.get_intraday_quote(ticker)
    spot = quote.price if quote is not None else None
    if spot is None:
        latest_rv = repo.fetch_realized_vol_latest(ticker)
        spot = latest_rv.get("price") if latest_rv else None
    if spot is None:
        logger.warning(
            "cockpit_daily_snapshot: %s no spot available, skipping OI chain",
            ticker,
        )
        return

    rows = aggregate_chain_per_strike(
        contracts,
        spot=spot,
        max_pct_from_spot=oi_band_pct,
        max_dte_days=oi_max_dte,
        today=market_date,
    )
    repo.delete_option_chain_per_strike(ticker, market_date)
    n_rows = repo.upsert_option_chain_per_strike(ticker, market_date, rows)
    logger.info("cockpit_daily_snapshot: %s option_chain rows=%d", ticker, n_rows)
