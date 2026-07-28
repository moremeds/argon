"""Theta Harvester scan job — zero-UW ranking over the warm store."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from uw_scan.config import Settings
from uw_scan.scanners.theta_harvester import (
    RISK_FREE_RATE,
    ThetaCandidate,
    build_candidate,
    dealer_support,
    range_metrics,
    realized_vol,
    select_short_strangle,
)
from uw_scan.storage.repository import Repository
from uw_scan.storage.theta_harvester_repository import ThetaHarvesterRepository

log = logging.getLogger(__name__)


def scan_ticker(repo: Any, ticker: str, as_of: date) -> ThetaCandidate | None:
    """One best strangle for one ticker-session, or None when inputs are thin.

    Returning None is deliberate for missing price history / chain / IV: a
    partial HV window or a chainless ticker would produce a candidate whose
    gates mean something different from every other row.
    """
    closes = repo.load_closes(ticker, as_of, lookback=90)
    hv20 = realized_vol(closes, 20)
    if hv20 is None or hv20 <= 0:
        return None
    hv60 = realized_vol(closes, 60)

    spot = repo.load_spot(ticker, as_of)
    if spot is None or spot <= 0:
        return None

    structure = select_short_strangle(repo.load_chain(ticker, as_of), spot, as_of)
    if structure is None:
        return None

    # ATM IV is read AFTER the structure is chosen, at that structure's own
    # expiry — so the IV and the traded legs always describe the same session
    # and the same tenor. Reading it first (from iv_rank_history) is what let
    # a May IV be compared against July realised vol for 85 of 114 tickers.
    iv = repo.load_atm_iv(ticker, as_of, structure.expiry)
    if iv is None or iv <= 0:
        return None

    ranged = range_metrics(closes, hv20)
    if ranged is None:
        return None  # <22 closes: "unknown", not "maximally trending"
    trend_pct, range_score = ranged
    return build_candidate(
        ticker=ticker,
        as_of=as_of,
        structure=structure,
        spot=spot,
        iv=iv,
        hv20=hv20,
        hv60=hv60,
        trend_20d_pct=trend_pct,
        range_score=range_score,
        dealer=dealer_support(repo.load_gex_rows(ticker, as_of), spot),
        r=RISK_FREE_RATE,
    )


def theta_harvester_scan(
    *,
    repo: Repository,
    settings: Settings,
    as_of: date | None = None,
    tickers: list[str] | None = None,
) -> dict[str, Any]:
    """Scan the watchlist (or an explicit subset) and persist candidates.

    Candidates of EVERY verdict are persisted, not just THETA_HARVEST. The
    non-harvest rows are the control arm: short vol is positive-expectancy in
    most windows, so a positive harvest markout against zero is uninformative
    while harvest-versus-control is not.
    """
    th = ThetaHarvesterRepository(repo.conn, schema=settings.db_schema)
    target = as_of or th.latest_surface_date()
    if target is None:
        log.warning("theta_harvester_scan: no surface capture yet, nothing to scan")
        return {"tickers_scanned": 0, "candidates_written": 0, "harvest_count": 0}
    universe = tickers or th.active_tickers()

    candidates: list[ThetaCandidate] = []
    for ticker in universe:
        try:
            found = scan_ticker(th, ticker, target)
        except Exception as exc:  # one bad ticker must not abort the sweep
            log.exception("theta_harvester_scan: %s failed: %r", ticker, exc)
            continue
        if found is not None:
            candidates.append(found)

    written = th.upsert_candidates(candidates)
    harvest = sum(1 for c in candidates if c.verdict == "THETA_HARVEST")
    log.info(
        "theta_harvester_scan: as_of=%s scanned=%d written=%d harvest=%d",
        target,
        len(universe),
        written,
        harvest,
    )
    return {
        "as_of": str(target),
        "tickers_scanned": len(universe),
        "candidates_written": written,
        "harvest_count": harvest,
    }


def theta_harvester_markout(*, repo: Repository, settings: Settings) -> dict[str, Any]:
    """Re-mark existing candidates. Pure compute over the warm store; idempotent.

    This job only SCORES rows that already exist — it never creates candidates.
    After a wipe, or on first deploy, run
    scripts/backfill/theta_harvester_backfill.py or reads stay empty for weeks.
    """
    from uw_scan.reports.theta_harvester_markout import run_theta_markout

    th = ThetaHarvesterRepository(repo.conn, schema=settings.db_schema)
    return run_theta_markout(repo=th)
