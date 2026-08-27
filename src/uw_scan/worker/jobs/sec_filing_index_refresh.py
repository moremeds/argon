"""Mirror SEC's periodic-filing index for the fundamental universe.

Zero provider budget: SEC is free and keyless, so this job never touches the UW
governor and never competes with a scan for calls. It is rate-limited only by
SEC's own 10 req/s ceiling, which the sleep below stays well under.

The job is resumable and cheap to re-run: filings are accession-keyed with
`ON CONFLICT DO NOTHING`, so a second pass over the same issuer writes zero rows
and costs one HTTP call. `--only-missing` skips issuers already in the index
entirely, which is what makes a nightly refresh affordable.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from typing import Any

import psycopg

from uw_scan.sources.sec_submissions import (
    fetch_cik_map,
    fetch_filings,
    sec_client,
)
from uw_scan.storage.fundamental_obs import FundamentalObsRepository
from uw_scan.storage.sec_filing_index import SecFilingIndexRepository

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = "argon-research chenxi lcxxcllcx@gmail.com"

#: 0.15s between issuers keeps us under SEC's 10 req/s even when an issuer needs
#: several archive fetches. Deliberately conservative: a 403 for rate abuse would
#: poison the whole run, and this job has no deadline.
_SLEEP_SECONDS = 0.15


def sec_filing_index_refresh(
    *,
    conn: psycopg.Connection,
    schema: str = "uw_scan",
    tickers: Sequence[str] | None = None,
    tier: str = "ranked",
    user_agent: str = DEFAULT_USER_AGENT,
    only_missing: bool = False,
    client: Any | None = None,
) -> dict[str, int]:
    """Fetch and persist SEC filings. Returns counters; never raises on network."""
    obs = FundamentalObsRepository(conn, schema)
    repo = SecFilingIndexRepository(conn, schema)

    names = [t.upper() for t in (tickers or obs.list_universe(tier))]
    counters = {
        "tickers": 0,
        "filings_inserted": 0,
        "no_cik": 0,
        "no_filings": 0,
        "skipped_present": 0,
        "failed": 0,
    }
    if not names:
        return counters

    owns_client = client is None
    client = client or sec_client(user_agent)
    try:
        cik_map = fetch_cik_map(client)
        if cik_map:
            repo.upsert_cik_map(cik_map)
        else:
            # The map fetch failing is the one error worth aborting on: every
            # per-issuer call needs a CIK, so continuing would just log 400
            # identical "no_cik" lines and look like a universe problem.
            logger.warning("sec cik map empty; aborting refresh")
            counters["failed"] = len(names)
            return counters

        present = repo.indexed_tickers() if only_missing else set()

        for ticker in names:
            if ticker in present:
                counters["skipped_present"] += 1
                continue
            counters["tickers"] += 1
            cik = cik_map.get(ticker)
            if not cik:
                counters["no_cik"] += 1
                continue
            filings = fetch_filings(client, cik)
            if not filings:
                counters["no_filings"] += 1
                time.sleep(_SLEEP_SECONDS)
                continue
            counters["filings_inserted"] += repo.record_filings(cik, ticker, filings)
            time.sleep(_SLEEP_SECONDS)
    finally:
        if owns_client:
            client.close()

    logger.info("sec_filing_index_refresh: %s", counters)
    return counters
