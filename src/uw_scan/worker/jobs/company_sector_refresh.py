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

COST, AND WHY IT RUNS DAILY
---------------------------
One call per ticker, once per ticker: the whole universe on the first run (450
distinct names 2026-08-20 — `fundamental_universe` holds 475 rows for them,
one per tier) against a 120k/day budget. Names already carrying a row are never
re-asked, including those the vendor could not classify (a recorded NULL is an
answer), so the second run and every run after it costs zero UW calls and one
indexed SELECT.

That asymmetry is the whole argument for a daily cron on a value that changes
at most once a quarter. The cost of running it is not the cadence but the
number of unfilled names, which only ever goes down. Monthly bought nothing and
cost a 31-day window in which the vendor pass reads an empty table and silently
routes AXP/COF/FLG on the pooled default — including the window right after the
deploy that ships it.

It asks every name without a row, NOT only the 265 with no chain sector, and
that is deliberate. `SECTOR_TO_TYPE` is prefix-matched, so a name carrying a
chain sector the map has no rule for (`Consumer`, `Healthcare`) still falls
through to the vendor pass — 337 of the 450 can reach it. Fetching only the
sectorless names would blind exactly that fallthrough. The 113 whose chain
sector does match a rule are the only wasted calls, once each, forever.
"""

from __future__ import annotations

import logging
from typing import Any

import psycopg

from uw_scan.api.client import UwClient
from uw_scan.api.endpoints import EndpointSlug
from uw_scan.storage.company_sector import CompanySectorRepository

log = logging.getLogger(__name__)

#: Ceiling on one run. Bounds an unnoticed universe explosion, NOT the normal
#: case — it sits above the 450-name universe on purpose. With a daily cron a
#: truncated run self-heals tomorrow, so this is a spend guard rather than a
#: correctness one; raise it with the universe, and the run logs when it binds.
DEFAULT_MAX_CALLS = 800


def parse_sector(body: Any) -> str | None:
    """The vendor's sector string, or None when it reports none.

    The `data` envelope is REAL even though `docs/uw-samples/unusual_whales_api_spec.yaml`
    declares `Ticker Info` flat: the live probe in `uw_api_capability_audit.json`
    records `/api/stock/{ticker}/info` as `body_kind: object:data-object`, and
    `normalize_etf_info` — production code against the structurally identical
    `Etf Info` — raises if `payload["data"]` is absent. Drop the envelope on the
    spec's word and this returns None for every ticker, which the job then stores
    as "the vendor has no sector" and never re-asks. Silent and permanent.

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
    # One over the cap, so "there was more" is observable rather than inferred
    # from `len(names) == max_calls` — which is also what a universe of exactly
    # `max_calls` looks like.
    names = repo.tickers_needing_fetch(max_calls + 1)
    totals = {"asked": 0, "classified": 0, "unclassified": 0, "failed": 0, "capped": 0}
    if not names:
        log.info("company_sector_refresh: nothing to fetch; %s", repo.coverage())
        return totals
    if len(names) > max_calls:
        # Never truncate quietly. A capped run looks exactly like a complete one
        # in the counters, and the cap binding at all means the universe grew
        # past what one run was sized for — worth seeing even though tomorrow's
        # run picks up the remainder.
        log.warning(
            "company_sector_refresh: capped at %d, more names still unfetched — "
            "the next daily run will continue; raise DEFAULT_MAX_CALLS to finish "
            "in one pass",
            max_calls,
        )
        names = names[:max_calls]
        totals["capped"] = 1

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
