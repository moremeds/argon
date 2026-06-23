# src/uw_scan/worker/jobs/option_surface_capture.py
"""Full-chain option-surface capture (nightly) and one-time historical backfill.

Forward-accumulates a durable per-strike IV/greeks grid for every watchlist ticker into
option_surface_grid_daily. UW returns 403 for per-strike history beyond ~30 days, so this
nightly capture is the only way the surface ever exists for future SVI/dislocation/
curvature work — every uncaptured night is permanently lost. Full chain: ALL expiries,
ALL strikes, no clip.

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
) -> list[dict]:
    """Fetch full-chain greeks for one ticker on market_date. date_iso=None → today."""
    gex_by_expiry = fetch_greek_exposure_by_expiry(
        client, repo, run_id, ticker, date=date_iso
    )
    expiries = sorted({r.expiry for r in gex_by_expiry if r.expiry >= market_date})
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
    *, repo: Repository, client: UwClient, today: _date | None = None
) -> int:
    """Capture the full option-chain IV/greeks grid for every watchlist ticker.

    Returns total rows written. ``today`` is the ET market date (the scheduler passes
    ``datetime.now(rth_tz).date()`` so a non-ET host does not stamp the next day).
    """
    cards = repo.list_watchlist_cards()
    if today is None:
        today = _date.today()
    written = 0
    for card in cards:
        ticker = card.ticker
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
    log.info("option_surface_capture wrote %d surface-grid rows", written)
    return written


def option_surface_backfill(
    *, repo: Repository, client: UwClient, days_back: int = 30
) -> int:
    """Fill option_surface_grid_daily for recent past weekdays not yet captured.

    Skips any market_date that already has rows in the table (idempotent).
    UW 403s beyond ~30 trading days; individual ticker/expiry 403s are logged and skipped.
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

    written = 0
    for market_date in dates:
        date_iso = market_date.isoformat()
        with repo.conn.cursor() as cur:
            cur.execute(
                f"SELECT 1 FROM {repo._schema}.option_surface_grid_daily WHERE market_date=%s LIMIT 1",
                (market_date,),
            )
            if cur.fetchone():
                log.info("backfill: %s already captured — skipping", date_iso)
                continue
        log.info("backfill: capturing %s (%d tickers)", date_iso, len(cards))
        for card in cards:
            ticker = card.ticker
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
    log.info("option_surface_backfill wrote %d rows total", written)
    return written
