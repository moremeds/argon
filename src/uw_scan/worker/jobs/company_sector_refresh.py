"""Fetch the vendor sector for universe names that carry none locally.

WHY THIS IS A JOB AND NOT PART OF ROUTING
-----------------------------------------
`fundamental_refresh` (18:20 ET) chains routing -> subscores -> anchor bands, and
its documented property is that the whole chain costs zero provider spend. Routing
needs a sector for the universe names with no `watchlist` row, and the only source
is one UW call per ticker. Doing that inside the nightly job would trade a
zero-cost invariant away for a value that changes at most once a quarter.

WHAT IT IS FOR
--------------
Exactly one routing question the chain taxonomy cannot answer: is this a
deposit-funded financial? Measured 2026-08-19, eleven financials sat in the panel
routed to `unclassified` -> `sales_to_ev`; five were handed a `medium`-confidence
band and six refused, the same business model reaching both outcomes because
`debt - cash` is not a coherent quantity for a bank. Three of them (AXP, COF, FLG)
carry no watchlist sector at all, so no chain rule can reach them.
Full measurement: `docs/research/2026-08-19-valuation-refusal-anatomy/`.

COST
----
One call per ticker, once per ticker, ~261 names at first run against a 120k/day
budget. Names already carrying a row are never re-asked, including those the
vendor could not classify (a recorded NULL is an answer) — so the steady state is
a handful of calls a month as the universe grows.
"""

from __future__ import annotations

import logging
from typing import Any

import psycopg

from uw_scan.api.client import UwClient
from uw_scan.api.endpoints import EndpointSlug
from uw_scan.storage.company_sector import CompanySectorRepository

log = logging.getLogger(__name__)

#: Ceiling on one run. The universe grows by tens, not thousands, so this bounds
#: an unnoticed universe explosion rather than the normal case.
DEFAULT_MAX_CALLS = 400


def parse_sector(body: Any) -> str | None:
    """The vendor's sector string, or None when it reports none.

    Pure so it can be tested against a real captured payload without a client.
    An empty string is normalised to None: the caller stores one shape for "the
    vendor cannot classify this name", and a stored `""` would route through
    `VENDOR_SECTOR_TO_TYPE` lookups as a distinct key that matches nothing.
    """
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, dict):
        return None
    sector = data.get("sector")
    if not isinstance(sector, str) or not sector.strip():
        return None
    return sector.strip()


def company_sector_refresh(
    *,
    conn: psycopg.Connection,
    client: UwClient,
    schema: str = "uw_scan",
    max_calls: int = DEFAULT_MAX_CALLS,
) -> dict[str, int]:
    """Fill missing vendor sectors. Returns counters."""
    repo = CompanySectorRepository(conn, schema=schema)
    names = repo.tickers_needing_fetch(max_calls)
    totals = {"asked": 0, "classified": 0, "unclassified": 0, "failed": 0}
    if not names:
        log.info("company_sector_refresh: nothing to fetch; %s", repo.coverage())
        return totals

    for ticker in names:
        try:
            resp, _ = client.get(EndpointSlug.STOCK_INFO, ticker=ticker)
            if resp.status_code != 200:
                log.warning(
                    "company_sector_refresh: HTTP %s for %s", resp.status_code, ticker
                )
                totals["failed"] += 1
                continue
            sector = parse_sector(resp.json())
            # Written even when None — see the migration: "asked and the vendor
            # had nothing" must be distinguishable from "not asked yet", or this
            # job re-asks the same unanswerable names every run forever.
            repo.upsert(ticker, sector)
            totals["asked"] += 1
            totals["classified" if sector else "unclassified"] += 1
        except Exception:
            # One bad ticker must not abort the run; the write path is an upsert,
            # so a partial pass is resumable by simply running again.
            totals["failed"] += 1
            log.exception("company_sector_refresh: %s failed", ticker)

    log.info("company_sector_refresh: %s | %s", totals, repo.coverage())
    return totals
