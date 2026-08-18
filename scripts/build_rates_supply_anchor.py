#!/usr/bin/env python
"""Add the real Treasury coupon-supply anchor the rates engine's supply factor needs.

The supply-pressure scenario froze the yield leg -- nominal up 41bp with inflation
compensation flat -- but nothing about supply, which is the half of
``supply_pressure_without_macro_confirmation`` that makes it a claim rather than a
mood.  Its window is the 2023 refunding episode, where Treasury raised coupon auction
sizes for the first time in five quarters, so the evidence exists and is public.

``available_at`` is the **announcement** date, not the auction date.  Treasury states
the size at the quarterly refunding announcement roughly a week before it sells the
paper, and that announcement is when the size became knowable.

One publisher quirk worth recording: ``TA_WS/securities/auctioned`` accepts
``startDate``/``endDate`` and ignores them, returning the same rolling 250 rows per
security type either way.  A caller that trusts the parameters gets whatever the window
happens to contain and cannot tell the difference, so this script filters client-side
and asserts the window it needs is actually covered.

Reproduce::

    uv run python scripts/build_rates_supply_anchor.py \
        --fixture tests/fixtures/macro/inflation_rates_golden.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import httpx

AUCTIONS_URL = "https://www.treasurydirect.gov/TA_WS/securities/auctioned"
UA = {"User-Agent": "argon-macro-fixture-author/0.1 (personal research desk)"}

#: The two coupon tenors whose size sets long-end supply pressure.
TENORS = ("10-Year", "30-Year")
#: Six quarters: the episode plus four flat quarters of baseline before it.
BASELINE_START = "2022-01"
SCENARIO = "supply_pressure_with_neutral_macro"


def fetch_refunding_sizes() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with httpx.Client(timeout=45.0, headers=UA) as client:
        for security_type in ("Note", "Bond"):
            response = client.get(
                AUCTIONS_URL, params={"format": "json", "type": security_type}
            )
            response.raise_for_status()
            rows.extend(response.json())

    selected = [
        {
            "security_term": row["securityTerm"],
            "auction_date": row["auctionDate"][:10],
            "available_at": row["announcementDate"][:10],
            "offering_amount_usd": row["offeringAmount"],
            "reopening": row["reopening"],
        }
        for row in rows
        if row.get("securityTerm") in TENORS
        and row.get("reopening") == "No"
        and row.get("offeringAmount")
        and row["auctionDate"][:7] >= BASELINE_START
    ]
    selected.sort(key=lambda row: (row["auction_date"], row["security_term"]))
    return selected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    args = parser.parse_args()

    fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
    scenario = next(row for row in fixture["scenarios"] if row["id"] == SCENARIO)
    as_of = scenario["as_of"]

    rows = [row for row in fetch_refunding_sizes() if row["available_at"] <= as_of]
    covered = {row["auction_date"][:7] for row in rows}
    assert {"2023-08", "2023-11"} <= covered, (
        "the rolling auction window no longer reaches the 2023 refunding episode; "
        f"it now covers {min(covered)}..{max(covered)}"
    )

    by_tenor: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_tenor.setdefault(row["security_term"], []).append(row)

    scenario["supply_history"] = {
        "source": "treasurydirect",
        "source_kind": "official",
        "cost_class": "free_official",
        "unit": "usd_offering_amount",
        "causal_role": "supply",
        "note": (
            "New-issue quarterly refunding sizes only; reopenings are excluded because "
            "a reopening adds to an existing security and its size is not comparable "
            "to a new issue's."
        ),
        "auctions": by_tenor,
    }
    args.fixture.write_text(json.dumps(fixture, indent=2) + "\n", encoding="utf-8")
    print(
        f"{SCENARIO}: "
        + ", ".join(f"{tenor} n={len(items)}" for tenor, items in by_tenor.items())
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
