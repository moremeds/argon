"""Nightly full-chain option-surface capture for a research cohort.

WHY THIS IS A JOB AND NOT A ONE-OFF SCRIPT
------------------------------------------
`option_surface_grid_daily` accrues FORWARD ONLY. UW serves ~180 calendar days of
history; past that the sole record is whatever was captured on the night. A
one-time backfill therefore buys a research cohort ~6 months of history and then
the series stops dead — and six months later that history has aged out of UW and
cannot be recovered at any price.

So the cohort is captured nightly alongside the watchlist. That is the difference
between a snapshot that decays and a dataset that compounds.

WHY FULL CHAIN, WHEN THE BACKFILL CAPS AT 60 DTE
------------------------------------------------
The historical backfill caps DTE because it pays per expiry across 25 sessions at
once and the strategy only trades 7-45 DTE. Going forward the calculus inverts:
the marginal cost is ~10 extra calls per ticker-night, and an expiry not captured
tonight is unrecoverable. Cheap insurance against a future study that wants the
term structure. ~37 tickers x ~18.3 calls = ~680 calls/night, about 0.6% of the
120k daily account budget.

SELF-GATING
-----------
An unseeded or unknown cohort yields no tickers and the job returns having spent
nothing. Enabling the flag before seeding is a no-op, not an error.
"""

from __future__ import annotations

import logging
from datetime import date as _date

from uw_scan.api.client import UwClient
from uw_scan.storage.repository import Repository
from uw_scan.storage.research_universe import ResearchUniverseRepository
from uw_scan.worker.jobs.option_surface_capture import _build_ticker_rows

log = logging.getLogger(__name__)


def option_surface_research_capture(
    *,
    repo: Repository,
    client: UwClient,
    cohort: str,
    today: _date | None = None,
    max_dte: int | None = None,
) -> int:
    """Capture the full chain for every ticker in `cohort`. Returns rows written.

    `today` is the ET market date — the scheduler passes
    ``datetime.now(rth_tz).date()`` so a non-ET host cannot stamp the next day.
    """
    if today is None:
        today = _date.today()
    tickers = ResearchUniverseRepository(
        repo.conn, schema=repo._schema
    ).list_cohort_tickers(cohort)
    if not tickers:
        log.info(
            "option_surface_research_capture: cohort %r is empty — nothing to do",
            cohort,
        )
        return 0

    written = 0
    for ticker in tickers:
        run_id = None
        try:
            run_id = repo.insert_scan_run(
                ticker, notes="option_surface_research_capture"
            )
            rows = _build_ticker_rows(
                client=client,
                repo=repo,
                run_id=run_id,
                ticker=ticker,
                market_date=today,
                date_iso=None,
                max_dte=max_dte,
            )
            # spot=None: UW's greeks payload carries no underlying, and daily_ohlc
            # is back-adjusted against as-traded strikes. Downstream `load_spot`
            # resolves this via its strike-range guard — filling it from OHLC here
            # would inject the very scale seam that guard exists to reject.
            n = repo.upsert_option_surface_grid(ticker, today, None, rows)
            repo.finish_scan_run(run_id, status="ok")
            repo.conn.commit()
            written += n
        except Exception as exc:  # noqa: BLE001 — one bad ticker must not kill the job
            repo.conn.rollback()
            log.warning(
                "option_surface_research_capture: %s skipped: %s", ticker, repr(exc)
            )
            if run_id is not None:
                repo.finish_scan_run(run_id, status="failed")
    log.info(
        "option_surface_research_capture[%s]: %d tickers -> %d rows",
        cohort,
        len(tickers),
        written,
    )
    return written
