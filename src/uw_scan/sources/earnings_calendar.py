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
"""

from __future__ import annotations

import logging
from datetime import date

from uw_scan.api.client import UwClient
from uw_scan.api.endpoints import EndpointSlug

log = logging.getLogger(__name__)

SLOTS: tuple[EndpointSlug, ...] = (
    EndpointSlug.EARNINGS_PREMARKET,
    EndpointSlug.EARNINGS_AFTERHOURS,
)

PAGE_SIZE = 100  # UW's documented maximum
MAX_PAGES = 8  # 800 names/slot/day, ~3x the busiest day observed


def fetch_calendar_symbols(
    client: UwClient, report_date: date, *, max_pages: int = MAX_PAGES
) -> set[str]:
    """Every symbol UW lists as reporting on `report_date`.

    Never raises. A slot that errors costs that slot's names for that day, which the
    backstop sweep recovers; letting it propagate would cost the whole run.
    """
    symbols: set[str] = set()
    for slot in SLOTS:
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
            symbols.update(
                str(row["symbol"]).strip().upper()
                for row in rows
                if row.get("symbol")
            )
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
    return symbols
