# src/uw_scan/worker/jobs/option_surface_capture.py
"""Full-chain option-surface capture (nightly) and one-time historical backfill.

Forward-accumulates a durable per-strike IV/greeks grid for every watchlist ticker into
option_surface_grid_daily. UW historical data is available for ~180 calendar days; after
that the only record is what was captured nightly — every uncaptured night is permanently
lost. Full chain: ALL expiries, ALL strikes, no clip.

One UW /greeks call per (ticker, expiry). Idempotent upsert (never delete) so a partial
re-run only adds. Per-ticker failure is isolated.
"""

from __future__ import annotations

import logging
from datetime import date as _date
from datetime import timedelta

from uw_scan.api.client import UwClient
from uw_scan.sources.uw import fetch_greek_exposure_by_expiry, fetch_greeks
from uw_scan.storage.repository import Repository

log = logging.getLogger(__name__)


def _build_ticker_rows(
    *,
    client: UwClient,
    repo: Repository,
    run_id: int,
    ticker: str,
    market_date: _date,
    date_iso: str | None,
    max_dte: int | None = None,
) -> list[dict]:
    """Fetch full-chain greeks for one ticker on market_date. date_iso=None → today.

    `max_dte` caps how far out the term structure is fetched. Cost here is one UW
    call PER EXPIRY (~17 per ticker-session unclipped, ~7.6 at 60 DTE), so the cap
    is the main lever on the price of a wide backfill. Default None = no cap, which
    is what the nightly capture wants: the archive is forward-only and an expiry
    not captured tonight is gone for good.
    """
    gex_by_expiry = fetch_greek_exposure_by_expiry(
        client, repo, run_id, ticker, date=date_iso
    )
    expiries = sorted({r.expiry for r in gex_by_expiry if r.expiry >= market_date})
    if max_dte is not None:
        expiries = [e for e in expiries if (e - market_date).days <= max_dte]
    rows: list[dict] = []
    for expiry in expiries:
        for r in fetch_greeks(
            client, repo, run_id, ticker, expiry.isoformat(), date=date_iso
        ):
            rows.append(
                {
                    "expiry": r.expiry,
                    "strike": r.strike,
                    "call_iv": r.call_volatility,
                    "put_iv": r.put_volatility,
                    "call_delta": r.call_delta,
                    "put_delta": r.put_delta,
                    "call_gamma": r.call_gamma,
                    "put_gamma": r.put_gamma,
                    "call_vega": r.call_vega,
                    "put_vega": r.put_vega,
                    "call_theta": r.call_theta,
                    "put_theta": r.put_theta,
                    "call_vanna": r.call_vanna,
                    "put_vanna": r.put_vanna,
                    "call_charm": r.call_charm,
                    "put_charm": r.put_charm,
                }
            )
    return rows


def option_surface_capture(
    *,
    repo: Repository,
    client: UwClient,
    today: _date | None = None,
    backfill_days: int = 0,
) -> int:
    """Capture the full option-chain IV/greeks grid for every watchlist ticker.

    Returns total rows written. ``today`` is the ET market date (the scheduler passes
    ``datetime.now(rth_tz).date()`` so a non-ET host does not stamp the next day).
    If backfill_days > 0, after today's capture the job fills that many additional
    oldest-uncaptured trading days (up to ~180 calendar days back), skipping any date
    already fully in the DB. Set via OPTION_SURFACE_BACKFILL_DAYS env var (default 4).
    """
    cards = repo.list_watchlist_cards()
    if today is None:
        today = _date.today()
    written = 0
    for card in cards:
        ticker = card.ticker
        run_id = None
        try:
            run_id = repo.insert_scan_run(ticker, notes="option_surface_capture")
            rows = _build_ticker_rows(
                client=client,
                repo=repo,
                run_id=run_id,
                ticker=ticker,
                market_date=today,
                date_iso=None,
            )
            n = repo.upsert_option_surface_grid(ticker, today, card.spot, rows)
            repo.finish_scan_run(run_id, status="ok")
            repo.conn.commit()
            written += n
        except Exception as exc:  # noqa: BLE001 — one bad ticker must not kill the job
            repo.conn.rollback()
            log.warning("option_surface_capture: %s skipped: %s", ticker, repr(exc))
            if run_id is not None:
                repo.finish_scan_run(run_id, status="failed")
    log.info("option_surface_capture wrote %d surface-grid rows", written)
    if backfill_days > 0:
        written += option_surface_backfill(
            repo=repo,
            client=client,
            days_back=130,  # ~180 calendar days
            max_dates=backfill_days,
        )
    return written


def option_surface_backfill(
    *,
    repo: Repository,
    client: UwClient,
    days_back: int = 130,
    end_date: _date | None = None,
    quota_limit: int | None = None,
    max_dates: int | None = None,
) -> int:
    """Fill option_surface_grid_daily for recent past weekdays not yet captured.

    Skips any market_date already fully captured (idempotent, per-ticker).
    end_date (inclusive) caps which dates are processed.
    quota_limit stops after the UW daily request counter reaches that value.
    max_dates stops after N dates that needed work (already-complete dates don't count).
    UW historical data is available for ~180 calendar days (~130 trading days).
    Returns total rows written.
    """
    today = _date.today()
    cards = repo.list_watchlist_cards()

    # Collect up to days_back weekdays ending yesterday, oldest first.
    dates: list[_date] = []
    d = today - timedelta(days=1)
    while len(dates) < days_back:
        if d.weekday() < 5:  # Mon–Fri
            dates.append(d)
        d -= timedelta(days=1)
    dates.reverse()
    if end_date is not None:
        dates = [d for d in dates if d <= end_date]

    written = 0
    dates_filled = 0
    for market_date in dates:
        date_iso = market_date.isoformat()
        with repo.conn.cursor() as cur:
            cur.execute(
                f"SELECT ticker FROM {repo._schema}.option_surface_grid_daily WHERE market_date=%s GROUP BY ticker",
                (market_date,),
            )
            done = {row[0] for row in cur.fetchall()}
        if len(done) >= len(cards):
            log.info("backfill: %s fully captured — skipping", date_iso)
            continue
        if max_dates is not None and dates_filled >= max_dates:
            log.info("backfill: max_dates=%d reached — stopping", max_dates)
            return written
        dates_filled += 1
        log.info(
            "backfill: capturing %s (%d/%d tickers remaining)",
            date_iso,
            len(cards) - len(done),
            len(cards),
        )
        for card in cards:
            ticker = card.ticker
            if ticker.upper() in done:
                continue
            if (
                quota_limit is not None
                and (client.rate_limit.daily_count or 0) >= quota_limit
            ):
                log.info("backfill: quota_limit=%d reached — stopping", quota_limit)
                return written
            run_id = None
            try:
                run_id = repo.insert_scan_run(ticker, notes="option_surface_backfill")
                rows = _build_ticker_rows(
                    client=client,
                    repo=repo,
                    run_id=run_id,
                    ticker=ticker,
                    market_date=market_date,
                    date_iso=date_iso,
                )
                n = repo.upsert_option_surface_grid(ticker, market_date, None, rows)
                repo.finish_scan_run(run_id, status="ok")
                repo.conn.commit()
                written += n
            except Exception as exc:  # noqa: BLE001 — isolate per ticker
                repo.conn.rollback()
                log.warning("backfill: %s/%s skipped: %s", date_iso, ticker, repr(exc))
                if run_id is not None:
                    repo.finish_scan_run(run_id, status="failed")
    log.info("option_surface_backfill wrote %d rows total", written)
    return written
