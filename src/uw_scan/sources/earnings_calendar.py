"""The UW earnings calendar for one session, across both classified slots.

WHAT THIS IS NOT
----------------
It is not the whole calendar. `premarket` and `afterhours` carry only the names whose
`report_time` UW has classified; a name it reports as `"unknown"` appears in NEITHER, and
there is no combined endpoint on our tier. Verified 2026-08-23 for ISRG, SONY, DJCO and
POET — none listed on its own report date despite 61-257 other names being listed that
day. The residual blind spot is ~2% of the statement-bearing universe, which is why the
monthly full sweep stays registered as a backstop rather than being replaced.
Method: `docs/research/2026-08-23-fundamental-filing-date-recovery/VERDICT.md` F4.

WHY IT PAGINATES
----------------
Peak days return more than one page — 202 premarket and 257 afterhours rows on
2026-08-06. A single-page fetch would silently drop the tail on exactly the days that
matter most, which is the failure shape this repo keeps paying for: not a crash, a
quiet subtraction.

WHY `fetch_calendar_listings` EXISTS BESIDE `fetch_calendar_symbols`
---------------------------------------------------------------------
`fetch_calendar_symbols` collapses both slots into one `set[str]`, which is exactly what
the original scan-target lookup needed and exactly what throws away the one fact the
durable calendar (spec §5-i) needs to persist: which slot a name was listed in.
`fetch_calendar_listings` is the shared implementation — `fetch_calendar_symbols` is now
`{l.symbol for l in fetch_calendar_listings(...)}`, so its own pagination, per-slot
failure isolation, and page-budget behaviour are inherited rather than duplicated.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

from uw_scan.api.client import UwClient
from uw_scan.api.endpoints import EndpointSlug

log = logging.getLogger(__name__)

SLOTS: tuple[EndpointSlug, ...] = (
    EndpointSlug.EARNINGS_PREMARKET,
    EndpointSlug.EARNINGS_AFTERHOURS,
)

# The session label persisted for each slot. Keys are exactly `SLOTS` — anything that
# iterates one should be able to trust it covers the other.
SESSION_BY_SLOT: dict[EndpointSlug, str] = {
    EndpointSlug.EARNINGS_PREMARKET: "premarket",
    EndpointSlug.EARNINGS_AFTERHOURS: "afterhours",
}

PAGE_SIZE = 100  # UW's documented maximum
MAX_PAGES = 8  # 800 names/slot/day, ~3x the busiest day observed


@dataclass(frozen=True)
class CalendarListing:
    symbol: str
    session: str  # "premarket" | "afterhours"


def fetch_calendar_listings(
    client: UwClient, report_date: date, *, max_pages: int = MAX_PAGES
) -> list[CalendarListing]:
    """Every (symbol, session) UW lists as reporting on `report_date`.

    Never raises. A slot that errors costs that slot's names for that day, which the
    backstop sweep recovers; letting it propagate would cost the whole run.
    """
    listings: list[CalendarListing] = []
    seen: set[tuple[str, str]] = set()
    for slot in SLOTS:
        session = SESSION_BY_SLOT[slot]
        for page in range(max_pages):
            try:
                resp, _ = client.get(
                    slot,
                    params={
                        "date": report_date.isoformat(),
                        "limit": PAGE_SIZE,
                        "page": page,
                    },
                )
            except Exception:
                log.exception("earnings_calendar: %s failed for %s", slot, report_date)
                break
            if resp.status_code != 200:
                log.warning(
                    "earnings_calendar: %s HTTP %s for %s",
                    slot,
                    resp.status_code,
                    report_date,
                )
                break
            rows = resp.json().get("data") or []
            for row in rows:
                if not row.get("symbol"):
                    continue
                symbol = str(row["symbol"]).strip().upper()
                key = (symbol, session)
                if key in seen:
                    continue
                seen.add(key)
                listings.append(CalendarListing(symbol=symbol, session=session))
            if len(rows) < PAGE_SIZE:
                break
        else:
            # Ran the page budget out without a short page: the tail is unread, and
            # saying so is the difference between a known gap and a silent one.
            log.warning(
                "earnings_calendar: %s hit the %d-page cap for %s — tail unread",
                slot,
                max_pages,
                report_date,
            )
    return listings


def fetch_calendar_symbols(
    client: UwClient, report_date: date, *, max_pages: int = MAX_PAGES
) -> set[str]:
    """Every symbol UW lists as reporting on `report_date`, session collapsed.

    Never raises — see `fetch_calendar_listings`, whose loop body this delegates to.
    """
    return {
        listing.symbol
        for listing in fetch_calendar_listings(client, report_date, max_pages=max_pages)
    }
