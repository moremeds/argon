"""Insert-or-touch semantics for revenue-breakdown observations (migration 122).

Same immutability contract as migration 114, tested the same way: an unchanged
recapture bumps one timestamp and writes no fact, a restatement lands BESIDE its
predecessor rather than replacing it, and the read path returns the current
answer while the superseded row stays available to anyone asking what changed.

Figures are NVDA's real 2026-04-26 reportable-segment rows, frozen.
"""

from __future__ import annotations

from uw_scan.storage.fundamental_concentration import RevenueBreakdownRepository
from uw_scan.worker.jobs.fundamental_concentration_capture import build_rows

# Real UW rev_breakdown rows, fetched 2026-08-18. The ConsolidationItemsAxis
# scope tag rides along exactly as the provider sends it: stripping it is a
# derivation decision and must not happen on the write path.
NVDA_SEGMENTS = [
    {
        "value": "74550000000.0",
        "members": [
            "us-gaap:OperatingSegmentsMember",
            "nvda:ComputeAndNetworkingSegmentMember",
        ],
        "field": "us-gaap:Revenues",
        "axis": ["srt:ConsolidationItemsAxis", "us-gaap:StatementBusinessSegmentsAxis"],
        "report_date": "2026-04-26",
        "rev_group": "product",
    },
    {
        "value": "7065000000.0",
        "members": ["us-gaap:OperatingSegmentsMember", "nvda:GraphicsSegmentMember"],
        "field": "us-gaap:Revenues",
        "axis": ["srt:ConsolidationItemsAxis", "us-gaap:StatementBusinessSegmentsAxis"],
        "report_date": "2026-04-26",
        "rev_group": "product",
    },
]

OLDER_PERIOD = [
    {**NVDA_SEGMENTS[0], "report_date": "2026-01-25", "value": "39331000000.0"}
]


def _repo(seeded) -> RevenueBreakdownRepository:
    return RevenueBreakdownRepository(seeded.conn, schema=seeded._schema)


def test_unchanged_recapture_writes_no_fact(seeded_db_empty_cards):
    repo = _repo(seeded_db_empty_cards)
    rows = build_rows("NVDA", NVDA_SEGMENTS)

    assert repo.record_rows(rows) == (2, 0)
    # The whole point of the monthly cadence: 11 recaptures a year must not
    # multiply the table by 12.
    assert repo.record_rows(rows) == (0, 2)


def test_restatement_lands_beside_its_predecessor(seeded_db_empty_cards):
    repo = _repo(seeded_db_empty_cards)
    repo.record_rows(build_rows("NVDA", NVDA_SEGMENTS))

    restated = [{**NVDA_SEGMENTS[0], "value": "74551000000.0"}, NVDA_SEGMENTS[1]]
    inserted, touched = repo.record_rows(build_rows("NVDA", restated))
    assert (inserted, touched) == (1, 1)

    with seeded_db_empty_cards.conn.cursor() as cur:
        cur.execute(
            f"SELECT count(*) FROM {seeded_db_empty_cards._schema}.revenue_breakdown_obs"
        )
        # 3, not 2: history is appended to, never overwritten.
        assert cur.fetchone()[0] == 3


def test_read_path_returns_the_current_answer_only(seeded_db_empty_cards):
    repo = _repo(seeded_db_empty_cards)
    repo.record_rows(build_rows("NVDA", NVDA_SEGMENTS))
    repo.record_rows(
        build_rows("NVDA", [{**NVDA_SEGMENTS[0], "value": "74551000000.0"}])
    )

    period = repo.periods("NVDA")["2026-04-26"]
    values = sorted(r["value"] for r in period)
    assert values == [7065000000.0, 74551000000.0]


def test_periods_are_newest_first_and_capped(seeded_db_empty_cards):
    repo = _repo(seeded_db_empty_cards)
    repo.record_rows(build_rows("NVDA", NVDA_SEGMENTS + OLDER_PERIOD))

    assert list(repo.periods("NVDA")) == ["2026-04-26", "2026-01-25"]
    assert list(repo.periods("NVDA", limit=1)) == ["2026-04-26"]


def test_unknown_ticker_reads_empty(seeded_db_empty_cards):
    assert _repo(seeded_db_empty_cards).periods("NVDA") == {}
