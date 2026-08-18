"""Revenue-concentration derivation, against two hand-verified filers.

Rows are REAL `rev_breakdown` payloads from UW, fetched 2026-08-18 and frozen
under `tests/fixtures/fundamentals/`. Nothing here touches the network, and
there are no placeholder tickers or round-number values.

NVDA and AVGO are the two filers whose breakdowns were reconciled by hand when
the retracted 0/257 computability verdict was overturned, which is why they are
the fixtures: their expected shares are evidence, not expectations.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import pytest

from uw_scan.fundamentals.concentration import (
    ANNUAL_MULTIPLE,
    annual_flags,
    partition,
    period_total,
    real_axis,
    shares_for_period,
)

FIXTURES = Path("tests/fixtures/fundamentals")


def _periods(ticker: str) -> dict[str, list[dict]]:
    doc = json.loads((FIXTURES / f"rev_breakdown_{ticker}.json").read_text())
    out: dict[str, list[dict]] = defaultdict(list)
    for row in doc["rows"]:
        out[row["report_date"]].append(row)
    return dict(out)


# --------------------------------------------------------------------------
# The two hand-reconciled filers
# --------------------------------------------------------------------------


def test_nvda_segment_prefers_asc280_axis() -> None:
    out = shares_for_period(_periods("nvda")["2026-04-26"])
    segment = out["axes"]["segment"]
    assert segment["axis"] == "us-gaap:StatementBusinessSegmentsAxis"
    assert segment["top_member"] == "nvda:ComputeAndNetworkingSegmentMember"
    assert segment["top_share"] == pytest.approx(0.9134, abs=1e-4)

    geography = out["axes"]["geography"]
    assert geography["top_member"] == "country:US"
    assert geography["top_share"] == pytest.approx(0.7813, abs=1e-4)


def test_avgo_ambiguous_axes_resolve_to_reportable_segments() -> None:
    """AVGO publishes both a segment and a product cut; 76% vs 68% turns on which.

    The reportable-segment axis is what "segment concentration" means, so the
    preference order — not the data — is what settles it.
    """
    out = shares_for_period(_periods("avgo")["2026-05-03"])
    assert out["axes"]["segment"]["axis"] == "us-gaap:StatementBusinessSegmentsAxis"
    assert out["axes"]["segment"]["top_share"] == pytest.approx(0.6765, abs=1e-4)


# --------------------------------------------------------------------------
# The rules that retired a failure bucket each
# --------------------------------------------------------------------------


def test_scope_axis_is_stripped_and_the_row_survives() -> None:
    """srt:ConsolidationItemsAxis qualifies scope; it does not partition revenue.

    Treating it as a real axis made every ASC 280 segment row look like a
    two-axis cross-tabulation and discarded exactly the rows that matter.
    """
    row = {
        "axis": ["srt:ConsolidationItemsAxis", "us-gaap:StatementBusinessSegmentsAxis"],
        "members": [
            "srt:OperatingSegmentsMember",
            "nvda:ComputeAndNetworkingSegmentMember",
        ],
        "value": "1",
    }
    assert real_axis(row) == (
        "us-gaap:StatementBusinessSegmentsAxis",
        "nvda:ComputeAndNetworkingSegmentMember",
    )


def test_denominator_comes_from_an_untagged_row_in_any_rev_group() -> None:
    """The total belongs to the PERIOD. Scoping it per rev_group reported no_total."""
    rows = _periods("nvda")["2026-04-26"]
    groups = {r["rev_group"] for r in rows}
    assert len(groups) > 1, (
        "fixture must span several rev_groups for this to mean anything"
    )
    assert period_total(rows) == pytest.approx(81_615_000_000.0)


def test_single_member_partition_is_refused() -> None:
    """A lone member equal to the total makes the share 100% by construction.

    Values are NVDA's real 2026-04-26 total, rearranged into the degenerate shape
    — no filer in the fixtures publishes one, so the case has to be posed.
    """
    total = period_total(_periods("nvda")["2026-04-26"])
    rows = [
        {"axis": [], "members": [], "value": str(total), "rev_group": "segment"},
        {
            "axis": ["us-gaap:StatementBusinessSegmentsAxis"],
            "members": ["nvda:ComputeAndNetworkingSegmentMember"],
            "value": str(total),
            "rev_group": "segment",
        },
    ]
    assert "segment" not in shares_for_period(rows)["axes"]


def test_subset_search_is_off_by_default() -> None:
    """14% of resolutions come from the subset path, and only two were verified.

    A wrong-level partition returns a *plausible* share — the failure mode this
    lane has already paid for twice — so the default forfeits that coverage
    rather than publish a number nobody can audit.

    NVDA's product axis for 2026-04-26 is a real multi-level case: four members
    are published, and only a two-member subset reconciles to the period total.
    It never reaches the card, because the reportable-segment axis is preferred
    and resolves cleanly — which is the point. The subset path only ever fires on
    axes nobody hand-checked.
    """
    rows = _periods("nvda")["2026-04-26"]
    total = period_total(rows)
    members: dict[str, float] = {}
    for row in rows:
        hit = real_axis(row)
        if hit and hit[0] == "srt:ProductOrServiceAxis":
            members[hit[1]] = float(row["value"])
    assert len(members) == 4, "fixture must still carry the multi-level product axis"

    ordered = sorted(members.items(), key=lambda m: -m[1])
    assert partition(ordered, total, allow_subset=False) is None
    resolved = partition(ordered, total, allow_subset=True)
    assert resolved is not None
    assert resolved["level"] == "subset:2"


# --------------------------------------------------------------------------
# Annual contamination
# --------------------------------------------------------------------------

#: Periods carrying an annual total. Identified from the fixtures themselves:
#: each is several times its adjacent quarters and none of its quarterly member
#: rows reconcile against it.
ANNUAL_TRUTH = {
    "nvda": {
        "2021-01-31",
        "2022-01-30",
        "2023-01-29",
        "2024-01-28",
        "2025-01-26",
        "2026-01-25",
    },
    "avgo": {"2024-11-03"},
}


@pytest.mark.parametrize("ticker", sorted(ANNUAL_TRUTH))
def test_annual_periods_are_flagged_exactly(ticker: str) -> None:
    flags = annual_flags(_periods(ticker))
    assert {p for p, is_annual in flags.items() if is_annual} == ANNUAL_TRUTH[ticker]


def test_growth_alone_does_not_read_as_annual() -> None:
    """The regression this rule was rewritten for.

    NVDA's revenue grows 26x across the fixture, so its recent QUARTERLY totals
    clear 2.5x its lifetime median on growth alone. A global-median baseline
    caught 3 of 6 annual periods and raised 3 false positives; the baseline has
    to be local for the multiple to mean anything.
    """
    periods = _periods("nvda")
    totals = {p: period_total(rows) for p, rows in periods.items()}
    lifetime = sorted(t for t in totals.values() if t)
    lifetime_median = lifetime[len(lifetime) // 2]

    # A real quarter that a global-median rule would have mislabelled.
    quarter = totals["2026-04-26"]
    assert quarter > ANNUAL_MULTIPLE * lifetime_median
    assert annual_flags(periods)["2026-04-26"] is False
