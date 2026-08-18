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
    DERIVATION_VERSION,
    annual_flags,
    build_card,
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


# --------------------------------------------------------------------------
# The card payload
# --------------------------------------------------------------------------


def test_dropped_periods_land_on_the_filers_fiscal_year_end() -> None:
    """The strongest available check that annual detection found annual figures.

    Neither filer's fiscal calendar is an input to the rule — it sees only
    totals and their neighbours. NVDA's fiscal year ends in late January and
    AVGO's in early November, so a detector picking out annual totals must drop
    periods in that month and no other.

    The converse does NOT hold, and asserting it was wrong: the fiscal-year-end
    month also hosts the filer's Q4 QUARTERLY figure. AVGO's 2025-11-02 (18.0B)
    is a real quarter and is correctly retained, while 2024-11-03 (51.6B) is the
    FY2024 total and is correctly dropped. A month-based rule would confuse the
    two; this one separates them by magnitude, which is the only thing that
    actually distinguishes them.
    """
    nvda = build_card(_periods("nvda"))
    assert {p[5:7] for p in nvda["dropped_annual_periods"]} == {"01"}
    assert len(nvda["dropped_annual_periods"]) == 6

    avgo = build_card(_periods("avgo"))
    assert avgo["dropped_annual_periods"] == ["2024-11-03"]
    assert "2025-11-02" in [p["report_date"] for p in avgo["trend"]]


def test_no_annual_figure_survives_into_the_trend() -> None:
    """Independent of the rule's own comparison: after filtering, no period may
    exceed its immediate predecessor by the annual multiple.

    The detector compares against a four-neighbour median, so an adjacent-pair
    check is a different measurement rather than a restatement of the rule. Real
    maxima on the frozen fixtures: NVDA 1.88x, AVGO 1.15x — an annual total left
    in a quarterly series lands near 4x and would fail this immediately.
    """
    for ticker in ("nvda", "avgo"):
        rows = _periods(ticker)
        kept = [p["report_date"] for p in build_card(rows)["trend"]]
        totals = [period_total(rows[p]) for p in kept]
        assert all(
            after < ANNUAL_MULTIPLE * before
            for before, after in zip(totals, totals[1:])
        )


def test_trend_accounts_for_every_captured_period() -> None:
    """Filtered, never lost. A period leaves the trend only by appearing in the
    dropped list, so a reader can reconcile the series against the filings."""
    for ticker in ("nvda", "avgo"):
        rows = _periods(ticker)
        card = build_card(rows)
        assert len(card["trend"]) + len(card["dropped_annual_periods"]) == len(rows)


def test_trend_is_oldest_first_and_latest_matches_the_headline() -> None:
    card = build_card(_periods("nvda"))
    dates = [p["report_date"] for p in card["trend"]]
    assert dates == sorted(dates)
    assert card["trend"][-1]["segment_top_share"] == card["segment"]["top_share"]
    assert card["segment"]["report_date"] == card["trend"][-1]["report_date"]


def test_unresolved_family_is_null_in_the_trend_never_zero() -> None:
    """AVGO resolves a geography cut in 5 of its 6 quarterly periods.

    The sixth must carry None. A 0.0 would render as "no geographic
    concentration", which is a fabricated fact about the company rather than a
    statement about what the filer disclosed.
    """
    card = build_card(_periods("avgo"))
    missing = [p for p in card["trend"] if p["geography_top_share"] is None]
    assert len(missing) == 1
    assert all(p["segment_top_share"] is not None for p in card["trend"])


def test_a_filer_with_no_breakdown_yields_no_families() -> None:
    """Absent, not zero, and not an exception — the common case for a filer that
    publishes no disaggregation at all."""
    card = build_card({"2026-04-26": [{"axis": [], "members": [], "value": 1.0}]})
    assert card["segment"] is None
    assert card["geography"] is None
    assert card["trend"] == [
        {
            "report_date": "2026-04-26",
            "segment_top_share": None,
            "geography_top_share": None,
        }
    ]


def test_derivation_version_travels_with_the_card() -> None:
    """The rules are new and one has already been corrected once. A rendered
    share that cannot say which derivation produced it is unauditable."""
    assert build_card(_periods("nvda"))["derivation_version"] == DERIVATION_VERSION
