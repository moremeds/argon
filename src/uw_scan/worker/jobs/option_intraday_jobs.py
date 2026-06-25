"""Per-minute option-contract intraday refresh for top OI movers.

For each watchlist ticker, finds the top-N option_symbols from the latest
``oi_change_top`` snapshot and fetches UW's per-minute intraday bars for the
session in which that OI built (``curr_date``). Persists raw 1-min buckets to
``option_intraday_buckets`` for downstream derivation (peak window, sparkline,
first/last trade) at API read time.

UW's OI delta is daily and published premarket at ~6:45 ET; this job is
scheduled at 9:00 ET so the new OI rows are present before we ask UW for the
intraday that produced them.

Single-flight via ``pg_try_advisory_lock``; per-ticker transactions commit on
success and roll back on failure so one bad ticker can't poison the next.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date

from uw_scan.api.client import UwClient
from uw_scan.config import Settings
from uw_scan.sources.uw import fetch_option_contract_intraday
from uw_scan.storage.option_intraday_repository import OptionIntradayBucketRepository
from uw_scan.storage.repository import Repository

logger = logging.getLogger(__name__)

INTRADAY_REFRESH_LOCK = 91502  # mnemonic: migration 049 + slot 02
INTRADAY_BACKFILL_LOCK = 91504  # operator historical sweep; distinct from daily 91502
DEFAULT_TOP_N = 10


def refresh_intraday_for_top_oi_movers(
    *,
    repo: Repository,
    client: UwClient,
    settings: Settings,
    ticker_filter: Callable[[str], bool] | None = None,
    top_n: int = DEFAULT_TOP_N,
    lock_key: int = INTRADAY_REFRESH_LOCK,
) -> dict[str, int]:
    """Fetch and persist intraday buckets for each watchlist ticker's top OI movers.

    Returns a small summary dict for logging:
    ``{"tickers": ..., "contracts": ..., "buckets": ...}``.
    """
    if not repo.try_advisory_lock(lock_key):
        logger.info("intraday_refresh: lock held; skipping this tick")
        return {"tickers": 0, "contracts": 0, "buckets": 0}

    intraday_repo = OptionIntradayBucketRepository(repo.conn, schema=settings.db_schema)
    tickers_seen = 0
    contracts_done = 0
    buckets_written = 0
    skipped_no_run = 0
    skipped_no_movers = 0
    contracts_empty = 0
    contracts_error = 0

    try:
        cards = repo.list_watchlist_cards()
        for card in cards:
            ticker = card.ticker
            if ticker_filter is not None and not ticker_filter(ticker):
                logger.debug(
                    "intraday_refresh: %s skipped outside this worker shard", ticker
                )
                continue
            tickers_seen += 1

            try:
                latest_run = repo.latest_run_id(ticker)
            except Exception as exc:
                logger.warning(
                    "intraday_refresh: %s latest_run_id failed: %s", ticker, repr(exc)
                )
                continue
            if not latest_run:
                logger.debug("intraday_refresh: %s has no completed run yet", ticker)
                skipped_no_run += 1
                continue

            top_rows = repo.fetch_oi_change_top(latest_run, limit=top_n)
            if not top_rows:
                logger.debug("intraday_refresh: %s no OI movers in latest run", ticker)
                skipped_no_movers += 1
                continue

            run_id = repo.insert_scan_run(ticker, notes="intraday_refresh")
            try:
                for row in top_rows[:top_n]:
                    option_symbol = row.get("option_symbol")
                    trade_date = row.get("curr_date")
                    if not option_symbol or trade_date is None:
                        continue

                    buckets = fetch_option_contract_intraday(
                        client,
                        repo,
                        run_id,
                        option_symbol,
                        trade_date.isoformat(),
                    )
                    n = intraday_repo.upsert_buckets(option_symbol, trade_date, buckets)
                    contracts_done += 1
                    buckets_written += n
                    if n == 0:
                        contracts_empty += 1
                    logger.info(
                        "intraday_refresh: %s %s %s buckets=%d",
                        ticker,
                        option_symbol,
                        trade_date,
                        n,
                    )

                repo.finish_scan_run(run_id, status="ok")
                repo.conn.commit()
            except Exception as exc:
                repo.conn.rollback()
                contracts_error += 1
                logger.exception("intraday_refresh: %s failed: %s", ticker, repr(exc))
    finally:
        repo.release_advisory_lock(lock_key)

    summary = {
        "tickers": tickers_seen,
        "contracts": contracts_done,
        "buckets": buckets_written,
        "skipped_no_run": skipped_no_run,
        "skipped_no_movers": skipped_no_movers,
        "contracts_empty": contracts_empty,
        "contracts_error": contracts_error,
    }
    logger.info(
        "intraday_refresh complete tickers=%d contracts=%d buckets=%d "
        "skipped_no_run=%d skipped_no_movers=%d contracts_empty=%d contracts_error=%d",
        summary["tickers"],
        summary["contracts"],
        summary["buckets"],
        summary["skipped_no_run"],
        summary["skipped_no_movers"],
        summary["contracts_empty"],
        summary["contracts_error"],
    )
    return summary


def backfill_intraday_history(
    *,
    repo: Repository,
    client: UwClient,
    settings: Settings,
    tickers: list[str],
    since: date,
    until: date,
    top_n: int = DEFAULT_TOP_N,
    lock_key: int = INTRADAY_BACKFILL_LOCK,
) -> dict[str, int]:
    """Operator one-shot: sweep intraday buckets for ``tickers`` across EVERY
    OI-mover session in ``[since, until]``.

    The daily ``refresh_intraday_for_top_oi_movers`` only fetches the latest
    run's session. This recovers history for tickers the #180 shard bug skipped,
    bounded by our own ``oi_change_events`` history (we can only fetch the tape
    for sessions whose movers we recorded) and UW's intraday retention. Per
    ``(ticker, session)`` transaction commits on success, rolls back on failure.
    Idempotent (upsert). Uses a distinct advisory lock so it never blocks the
    daily job.
    """
    if not repo.try_advisory_lock(lock_key):
        logger.info("intraday_backfill: lock held; skipping")
        return {"tickers": 0, "sessions": 0, "contracts": 0, "buckets": 0, "errors": 0}

    intraday_repo = OptionIntradayBucketRepository(repo.conn, schema=settings.db_schema)
    schema = settings.db_schema
    tickers_done = 0
    sessions_done = 0
    contracts_done = 0
    buckets_written = 0
    errors = 0

    try:
        for ticker in sorted({t.strip().upper() for t in tickers if t.strip()}):
            with repo.conn.cursor() as cur:
                cur.execute(
                    f"SELECT DISTINCT curr_date FROM {schema}.oi_change_events "
                    "WHERE underlying_symbol = %s AND curr_date BETWEEN %s AND %s "
                    "ORDER BY curr_date",
                    (ticker, since, until),
                )
                sessions = [r[0] for r in cur.fetchall()]
            if not sessions:
                logger.info("intraday_backfill: %s no mover sessions in window", ticker)
                continue
            tickers_done += 1

            for sess in sessions:
                # Top-N movers for this (ticker, session) — same notional ordering
                # the daily job's fetch_oi_change_top uses.
                with repo.conn.cursor() as cur:
                    cur.execute(
                        f"SELECT option_symbol FROM {schema}.oi_change_events "
                        "WHERE underlying_symbol = %s AND curr_date = %s "
                        "ORDER BY (COALESCE(volume, 0) * COALESCE(avg_price, 0)) "
                        "DESC NULLS LAST, rnk ASC LIMIT %s",
                        (ticker, sess, top_n),
                    )
                    movers = [r[0] for r in cur.fetchall()]
                if not movers:
                    continue

                run_id = repo.insert_scan_run(ticker, notes="intraday_backfill")
                try:
                    for option_symbol in movers:
                        buckets = fetch_option_contract_intraday(
                            client, repo, run_id, option_symbol, sess.isoformat()
                        )
                        n = intraday_repo.upsert_buckets(option_symbol, sess, buckets)
                        contracts_done += 1
                        buckets_written += n
                    repo.finish_scan_run(run_id, status="ok")
                    repo.conn.commit()
                    sessions_done += 1
                except Exception as exc:  # noqa: BLE001
                    repo.conn.rollback()
                    errors += 1
                    logger.warning(
                        "intraday_backfill: %s %s failed: %s", ticker, sess, repr(exc)
                    )
    finally:
        repo.release_advisory_lock(lock_key)

    summary = {
        "tickers": tickers_done,
        "sessions": sessions_done,
        "contracts": contracts_done,
        "buckets": buckets_written,
        "errors": errors,
    }
    logger.info(
        "intraday_backfill complete tickers=%d sessions=%d contracts=%d buckets=%d errors=%d",
        summary["tickers"],
        summary["sessions"],
        summary["contracts"],
        summary["buckets"],
        summary["errors"],
    )
    return summary
