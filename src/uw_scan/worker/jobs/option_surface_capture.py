# src/uw_scan/worker/jobs/option_surface_capture.py
"""Full-chain option-surface capture.

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

from uw_scan.api.client import UwClient
from uw_scan.sources.uw import fetch_greek_exposure_by_expiry, fetch_greeks
from uw_scan.storage.repository import Repository

log = logging.getLogger(__name__)


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
            # Enumerate the FULL term structure from greek-exposure/expiry (one row
            # per listed expiry). NOT /option-contracts — UW caps that at the 500
            # highest-VOLUME contracts, dropping long-dated expiries (SPX 28/53 missing).
            gex_by_expiry = fetch_greek_exposure_by_expiry(client, repo, run_id, ticker)
            expiries = sorted({r.expiry for r in gex_by_expiry if r.expiry >= today})
            rows: list[dict] = []
            for expiry in expiries:
                for r in fetch_greeks(client, repo, run_id, ticker, expiry.isoformat()):
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
            n = repo.upsert_option_surface_grid(ticker, today, card.spot, rows)
            repo.finish_scan_run(run_id, status="ok")
            repo.conn.commit()
            written += n
        except Exception as exc:  # noqa: BLE001 — one bad ticker must not kill the job
            repo.conn.rollback()
            log.warning("option_surface_capture: %s skipped: %s", ticker, repr(exc))
    log.info("option_surface_capture wrote %d surface-grid rows", written)
    return written
