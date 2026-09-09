"""Capture UW's economic calendar and fill verified FRED actuals. See
migration 149, `storage/macro_release_calendar.py`, `reports/macro_releases.py`.
"""

from __future__ import annotations

import logging

from uw_scan.reports.macro_releases import fill_actuals
from uw_scan.sources.fred import FredProvider
from uw_scan.sources.uw import UwClient, fetch_economic_calendar
from uw_scan.storage.macro_release_calendar import MacroReleaseCalendarRepository
from uw_scan.storage.repository import Repository

logger = logging.getLogger(__name__)

#: Market-wide fetch, no ticker -- same sentinel convention as discovery_scan.
_RUN_TICKER = "_MACRO_RELEASES"


def macro_release_calendar_capture(
    repo: Repository, client: UwClient, fred_api_key: str | None
) -> dict[str, int]:
    """One UW call (current + next week) upserted, then a FRED fill pass over
    every past, unfilled, mapped row. Returns `{"captured": n, "filled": n}`.
    Filling is skipped (not an error) when no `FRED_API_KEY` is configured --
    the calendar capture stays useful without it."""
    releases_repo = MacroReleaseCalendarRepository(repo.conn, schema=repo._schema)
    run_id = repo.insert_scan_run(_RUN_TICKER, notes="macro_release_calendar_capture")
    try:
        rows = fetch_economic_calendar(client, repo, run_id)
        captured = releases_repo.upsert_captured_rows(rows)
        repo.finish_scan_run(run_id, status="ok")
        repo.conn.commit()
    except Exception:
        repo.finish_scan_run(run_id, status="error")
        repo.conn.commit()
        raise

    filled = 0
    if fred_api_key:
        with FredProvider(
            api_key=fred_api_key, job_name="macro_release_calendar"
        ) as fred:
            filled = fill_actuals(releases_repo, fred)
    else:
        logger.info("macro_release_calendar: FRED_API_KEY unset, skipping actual fill")

    return {"captured": captured, "filled": filled}
