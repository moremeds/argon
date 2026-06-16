"""Skew swing-DTE greeks refresh.

Per-strike call/put delta for a swing expiry (~21-60 DTE), single-names only. The
GEX/cockpit ``exposures_by_expiry_strike`` table holds front-expiry-only greeks for
single-names (only indices get multi-expiry via the cockpit), so the Skew tab's
strike-by-delta structure detail had no swing chain to pick wings from. This job
reuses the proven cockpit fetchers (``fetch_option_contracts`` → ``pick_target_expiries``
→ ``fetch_greeks``) and persists into the dedicated ``skew_swing_greeks`` table.

NOTE: it uses ``fetch_greeks`` (the ``/greeks`` endpoint — real per-contract OPTION delta
in [-1, 1]), NOT ``fetch_greek_exposure`` (``/greek-exposure`` returns delta *exposure*,
≈0 for low-OI strikes — unusable for target-delta strike selection).
"""

from __future__ import annotations

import logging
from datetime import date as _date

from uw_scan.api.client import UwClient
from uw_scan.cards.option_chain import pick_target_expiries
from uw_scan.cards.skew_first_principles import asset_class_baseline
from uw_scan.sources.uw import fetch_greeks, fetch_option_contracts
from uw_scan.storage.repository import Repository

log = logging.getLogger(__name__)

# Pick expiries bracketing the swing window so at least one usually lands in the
# deriver's [21, 60] DTE filter. One UW greek-exposure call per chosen expiry.
SWING_TARGET_DTES: tuple[int, ...] = (30, 45)
_CONTRACTS_LIMIT = 500


def skew_swing_greeks_refresh(*, repo: Repository, client: UwClient) -> int:
    """One swing-expiry per-strike greeks snapshot per non-index watchlist ticker.
    Idempotent per (ticker, market_date) via delete-then-insert. Returns rows written."""
    cards = repo.list_watchlist_cards()
    today = _date.today()
    written = 0
    for card in cards:
        ticker = card.ticker
        cls = asset_class_baseline(ticker, sector=card.sector)
        if cls["asset_class"] == "index_macro":
            # Structure detail is non-index only; indices already get cockpit chains.
            continue
        try:
            run_id = repo.insert_scan_run(ticker, notes="skew_swing_greeks")
            contracts = fetch_option_contracts(
                client, repo, run_id, ticker, limit=_CONTRACTS_LIMIT
            )
            expiries = pick_target_expiries(
                contracts, target_dtes=SWING_TARGET_DTES, today=today
            )
            rows: list[dict] = []
            for expiry in expiries:
                dte = (expiry - today).days  # GreeksRow has no dte; derive from expiry
                for r in fetch_greeks(client, repo, run_id, ticker, expiry.isoformat()):
                    rows.append(
                        {
                            "expiry": r.expiry,
                            "strike": r.strike,
                            "dte": dte,
                            "call_delta": r.call_delta,
                            "put_delta": r.put_delta,
                        }
                    )
            n = repo.upsert_skew_swing_greeks(ticker, today, rows)
            repo.finish_scan_run(run_id, status="ok")
            repo.conn.commit()
            written += n
        except Exception as exc:  # noqa: BLE001 — one bad ticker must not kill the job
            repo.conn.rollback()
            log.warning("skew_swing_greeks_refresh: %s skipped: %s", ticker, repr(exc))
    log.info("skew_swing_greeks_refresh wrote %d swing-greek rows", written)
    return written
