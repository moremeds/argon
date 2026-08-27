"""Resolving a disclosed segment to a chain: specificity, and refusing a tie.

The defect this file defends against shipped. `datacenter` (AI-Cloud/NeoCloud) is
a substring of `datacenterandcommunications` (Optical-Communication), and the
resolver took the FIRST alias an unordered SELECT returned, then broke. Coherent
disclosed its Datacom & Communications segment at 74.6% of revenue — the single
best-evidenced optical exposure argon holds — and it was filed under the cloud
chain, while the optical chain's only two magnitudes were an over-broad match on
a non-member and the smallest segment of a near-pure-play.
"""

from __future__ import annotations

import pytest

from uw_scan.storage.research_taxonomy import ResearchTaxonomyRepository
from uw_scan.worker.jobs.research_taxonomy_seed import (
    derive_disclosed_exposure,
    seed_aliases,
)

V = "alias-test-v1"


def _segments(conn, schema: str, rows: list[tuple[str, str, float]]) -> None:
    """One report date per ticker: an untagged consolidated row, plus members."""
    with conn.cursor() as cur:
        for i, (ticker, member, value) in enumerate(rows):
            cur.execute(
                f"""INSERT INTO {schema}.revenue_breakdown_obs
                        (source, ticker, report_date, rev_group, field, axis,
                         members, value, content_hash, payload_version, raw_jsonb)
                    VALUES ('uw', %s, DATE '2026-06-30', 'segment', 'revenue',
                            %s, %s, %s, %s, 'v1', '{{}}'::jsonb)""",
                (
                    ticker,
                    [] if member is None else ["us-gaap:StatementBusinessSegmentsAxis"],
                    [] if member is None else [member],
                    value,
                    f"h{i}-{ticker}-{member}",
                ),
            )
    conn.commit()


def _setup(conn, schema: str) -> ResearchTaxonomyRepository:
    tax = ResearchTaxonomyRepository(conn, schema=schema)
    tax.publish_version(V, note="alias specificity", activate=True)
    tax.define_chains(
        V,
        [
            {"domain": "optical", "chain": "Optical", "layer": "Module", "layer_rank": 10},
            {"domain": "cloud", "chain": "Cloud", "layer": "Hosting", "layer_rank": 10},
        ],
    )
    return tax


def test_the_longer_alias_wins_because_it_is_the_narrower_claim(
    seeded_db_empty_cards,
):
    conn, schema = seeded_db_empty_cards.conn, seeded_db_empty_cards._schema
    _setup(conn, schema)
    seed_aliases(
        conn,
        [
            {"chain": "Cloud", "pattern": "datacenter", "approved_by": "test"},
            {
                "chain": "Optical",
                "pattern": "datacenterandcommunications",
                "approved_by": "test",
                "role": "component",
            },
        ],
        schema=schema,
        version=V,
    )
    # Coherent's real shape: a consolidated total and one tagged segment.
    _segments(
        conn,
        schema,
        [
            ("COHR", None, 3627.0),
            ("COHR", "iivi:DatacenterAndCommunicationsSegmentMember", 2705.0),
        ],
    )

    counters = derive_disclosed_exposure(conn, schema=schema, version=V)
    assert counters["ambiguous"] == 0

    tax = ResearchTaxonomyRepository(conn, schema=schema)
    got = {
        (e["chain"], e["ticker"]): float(e["magnitude"])
        for e in tax.exposures(V)
        if e["magnitude"] is not None
    }
    assert ("Optical", "COHR") in got, "the narrower alias must win"
    assert ("Cloud", "COHR") not in got
    assert got[("Optical", "COHR")] == pytest.approx(2705.0 / 3627.0, rel=1e-9)


def test_an_equally_specific_tie_across_two_chains_is_refused(seeded_db_empty_cards):
    """No evidence breaks the tie, so nothing is written.

    A coin flip here publishes a magnitude that reads to the operator as
    disclosed fact.
    """
    conn, schema = seeded_db_empty_cards.conn, seeded_db_empty_cards._schema
    _setup(conn, schema)
    seed_aliases(
        conn,
        [
            {"chain": "Cloud", "pattern": "datacenter", "approved_by": "test"},
            {"chain": "Optical", "pattern": "datacenter", "approved_by": "test"},
        ],
        schema=schema,
        version=V,
    )
    _segments(
        conn,
        schema,
        [("MOD", None, 1000.0), ("MOD", "mod:DataCenterMember", 400.0)],
    )

    counters = derive_disclosed_exposure(conn, schema=schema, version=V)
    assert counters["ambiguous"] == 1
    assert counters["written"] == 0

    tax = ResearchTaxonomyRepository(conn, schema=schema)
    assert [e for e in tax.exposures(V) if e["magnitude"] is not None] == []


def test_one_ticker_may_carry_a_magnitude_in_each_of_two_chains(
    seeded_db_empty_cards,
):
    """The break-on-first-match also suppressed a second, larger exposure.

    HPE discloses both a Cloud/AI segment and a Data Center Networking segment.
    Under first-match-wins the 3.0% networking row claimed the cloud chain and
    the 72.2% Cloud/AI row was dropped by ON CONFLICT DO NOTHING.
    """
    conn, schema = seeded_db_empty_cards.conn, seeded_db_empty_cards._schema
    _setup(conn, schema)
    seed_aliases(
        conn,
        [
            {"chain": "Cloud", "pattern": "cloudai", "approved_by": "test"},
            {"chain": "Cloud", "pattern": "datacenter", "approved_by": "test"},
            {
                "chain": "Optical",
                "pattern": "datacenternetworking",
                "approved_by": "test",
            },
        ],
        schema=schema,
        version=V,
    )
    _segments(
        conn,
        schema,
        [
            ("HPE", None, 10000.0),
            ("HPE", "hpe:CloudAISegmentMember", 7218.0),
            ("HPE", "hpe:DataCenterNetworkingMember", 300.0),
        ],
    )

    derive_disclosed_exposure(conn, schema=schema, version=V)
    tax = ResearchTaxonomyRepository(conn, schema=schema)
    got = {
        (e["chain"], e["ticker"]): float(e["magnitude"])
        for e in tax.exposures(V)
        if e["magnitude"] is not None
    }
    assert got[("Cloud", "HPE")] == pytest.approx(0.7218, rel=1e-6)
    assert got[("Optical", "HPE")] == pytest.approx(0.03, rel=1e-6)
