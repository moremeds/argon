"""Versioned, replayable research reports (migration 141).

The gate this file defends: an answer given in August must still read exactly as
it did in August after September's data and October's engine arrive. Everything
else here — the supersede chain, the no-op republish, the traceability CHECK —
exists to keep that one property true.
"""

from __future__ import annotations

from datetime import date

import psycopg
import pytest

from uw_scan.fundamentals.report_delta import report_delta
from uw_scan.storage.research_reports import (
    STATUS_PUBLISHED,
    STATUS_SUPERSEDED,
    ResearchReportsRepository,
    content_hash,
)
from uw_scan.worker.jobs.research_report_assemble import (
    assemble_company_report,
    check_single_basis,
)

MANIFEST = {
    "engine_version": "fundamentals-v2:aaaaaaaa",
    "taxonomy_version": "argon-research-v1",
    "evidence_policy": "true_pit_only",
    "as_of": "2026-08-25",
    "scope": {"ticker": "NVDA"},
    "assembler_version": "report-assembler-v1",
}


def _blocks(priority: float = 1.20):
    return [
        {
            "ordinal": 0,
            "block_kind": "scope",
            "title": "NVDA — research scope",
            "payload": {"ticker": "NVDA"},
            "derivation": "the report manifest, restated for the reader",
        },
        {
            "ordinal": 1,
            "block_kind": "dimensions",
            "title": "Research-priority dimensions",
            "payload": {"priority": priority, "growth": 0.80},
            "evidence": {"source": "fundamental_dimensions"},
            "authority": "research_priority",
        },
    ]


def _repo(seeded) -> ResearchReportsRepository:
    return ResearchReportsRepository(seeded.conn, schema=seeded._schema)


def test_an_old_version_replays_unchanged_after_the_world_moves(seeded_db_empty_cards):
    """The whole product. v1 must read in November exactly as it read in August."""
    repo = _repo(seeded_db_empty_cards)
    v1 = repo.publish(
        report_key="company:NVDA",
        report_type="company",
        title="NVDA research report",
        manifest=MANIFEST,
        blocks=_blocks(1.20),
    )
    frozen_hash, frozen_blocks = v1["content_hash"], v1["blocks"]

    # New data AND a new method arrive.
    v2 = repo.publish(
        report_key="company:NVDA",
        report_type="company",
        title="NVDA research report",
        manifest={**MANIFEST, "engine_version": "fundamentals-v3:bbbbbbbb"},
        blocks=_blocks(0.10),
    )
    assert v2["version_no"] == 2

    replayed = repo.version("company:NVDA", 1)
    assert replayed["content_hash"] == frozen_hash
    assert replayed["blocks"] == frozen_blocks
    assert replayed["manifest_jsonb"]["engine_version"] == "fundamentals-v2:aaaaaaaa"


def test_the_predecessor_is_superseded_never_deleted(seeded_db_empty_cards):
    repo = _repo(seeded_db_empty_cards)
    v1 = repo.publish(
        report_key="company:AMD",
        report_type="company",
        title="AMD research report",
        manifest=MANIFEST,
        blocks=_blocks(1.0),
    )
    v2 = repo.publish(
        report_key="company:AMD",
        report_type="company",
        title="AMD research report",
        manifest=MANIFEST,
        blocks=_blocks(2.0),
    )
    old = repo.version("company:AMD", 1)
    assert old["status"] == STATUS_SUPERSEDED
    assert old["report_id"] == v1["report_id"]
    assert old["superseded_by"] == v2["report_id"]
    assert repo.latest("company:AMD")["version_no"] == 2


def test_a_refresh_that_found_nothing_publishes_no_version(seeded_db_empty_cards):
    """A version whose delta is empty is noise dressed as news."""
    repo = _repo(seeded_db_empty_cards)
    first = repo.publish(
        report_key="company:AVGO",
        report_type="company",
        title="AVGO research report",
        manifest=MANIFEST,
        blocks=_blocks(1.0),
    )
    again = repo.publish(
        report_key="company:AVGO",
        report_type="company",
        title="AVGO research report",
        manifest=MANIFEST,
        blocks=_blocks(1.0),
    )
    assert first["changed"] is True
    assert again["changed"] is False
    assert again["version_no"] == 1
    assert len(repo.versions("company:AVGO")) == 1


def test_the_delta_between_two_stored_versions_names_the_move(seeded_db_empty_cards):
    repo = _repo(seeded_db_empty_cards)
    repo.publish(
        report_key="company:MU",
        report_type="company",
        title="MU research report",
        manifest=MANIFEST,
        blocks=_blocks(1.20),
    )
    prev = repo.version("company:MU", 1)
    curr = repo.publish(
        report_key="company:MU",
        report_type="company",
        title="MU research report",
        manifest=MANIFEST,
        blocks=_blocks(0.10),
    )
    d = report_delta(prev, curr)
    assert d["is_first_version"] is False
    assert d["manifest"] == []
    moved = d["blocks"]["moved"]
    assert [m["block_kind"] for m in moved] == ["dimensions"]
    change = moved[0]["changes"][0]
    assert change["path"] == "priority"
    assert change["before"] == 1.20
    assert change["after"] == 0.10


def test_a_block_with_neither_evidence_nor_derivation_is_refused(
    seeded_db_empty_cards,
):
    """A number nobody can trace is the state this program exists to leave."""
    repo = _repo(seeded_db_empty_cards)
    with pytest.raises(psycopg.errors.CheckViolation):
        repo.publish(
            report_key="company:INTC",
            report_type="company",
            title="INTC research report",
            manifest=MANIFEST,
            blocks=[
                {
                    "ordinal": 0,
                    "block_kind": "dimensions",
                    "title": "untraceable",
                    "payload": {"priority": 1.0},
                }
            ],
        )
    seeded_db_empty_cards.conn.rollback()


def test_a_block_may_not_claim_investment_ranking(seeded_db_empty_cards):
    """The program ceiling is research_priority, enforced in the store."""
    repo = _repo(seeded_db_empty_cards)
    blocks = _blocks(1.0)
    blocks[1]["authority"] = "investment_ranking"
    with pytest.raises(psycopg.errors.CheckViolation):
        repo.publish(
            report_key="company:TSM",
            report_type="company",
            title="TSM research report",
            manifest=MANIFEST,
            blocks=blocks,
        )
    seeded_db_empty_cards.conn.rollback()


def test_mixed_bases_are_refused_before_anything_is_written():
    """Two engine versions in one report is two answers stapled together."""
    blocks = _blocks(1.0)
    blocks[1]["evidence"] = {"engine_version": "fundamentals-v1:cccccccc"}
    with pytest.raises(ValueError, match="a report carries ONE basis"):
        check_single_basis(MANIFEST, blocks)

    blocks[1]["evidence"] = {"engine_version": MANIFEST["engine_version"]}
    check_single_basis(MANIFEST, blocks)  # agreement passes

    blocks[1]["evidence"]["as_of"] = "2020-01-01"
    with pytest.raises(ValueError, match="is as-of"):
        check_single_basis(MANIFEST, blocks)


def test_the_assembler_is_deterministic_and_declares_its_gaps(seeded_db_empty_cards):
    """Same inputs, same hash — the property that makes replay checkable at all."""
    conn, schema = seeded_db_empty_cards.conn, seeded_db_empty_cards._schema
    kw = {"schema": schema, "as_of": date(2026, 8, 25), "publish": False}
    a = assemble_company_report(conn, "NVDA", **kw)
    b = assemble_company_report(conn, "NVDA", **kw)
    assert a["content_hash"] == b["content_hash"] == content_hash(a["blocks"])

    # A DB with no dimensions must SAY so rather than emit a short report that
    # reads complete.
    unsupported = next(b for b in a["blocks"] if b["block_kind"] == "unsupported")
    assert unsupported["ordinal"] == 1
    assert any("gap in Argon" in n for n in unsupported["payload"]["notes"])
    assert a["status"] == "partial"


def test_a_published_assembly_round_trips_through_the_store(seeded_db_empty_cards):
    conn, schema = seeded_db_empty_cards.conn, seeded_db_empty_cards._schema
    drafted = assemble_company_report(
        conn, "NVDA", schema=schema, as_of=date(2026, 8, 25), publish=False
    )
    stored = assemble_company_report(
        conn, "NVDA", schema=schema, as_of=date(2026, 8, 25), publish=True
    )
    assert stored["content_hash"] == drafted["content_hash"]
    assert stored["status"] == "partial"

    repo = _repo(seeded_db_empty_cards)
    fetched = repo.latest("company:NVDA")
    assert fetched["content_hash"] == drafted["content_hash"]
    assert [b["block_kind"] for b in fetched["blocks"]] == [
        b["block_kind"] for b in drafted["blocks"]
    ]
    assert fetched["status"] != STATUS_PUBLISHED  # partial, and honest about it


def test_a_chain_report_counts_companies_not_placements(seeded_db_empty_cards):
    """A name in two layers must not vote twice, nor inflate a numerator.

    `chain_membership` is grained (chain, layer, ticker). Counting rows where the
    coverage query counts distinct tickers produced a report whose
    `with_compatible_result` (19) exceeded its own `members` (17) — a numerator
    larger than its denominator, printed as fact.
    """
    from uw_scan.storage.research_taxonomy import ResearchTaxonomyRepository
    from uw_scan.worker.jobs.research_report_assemble import assemble_chain_report

    conn, schema = seeded_db_empty_cards.conn, seeded_db_empty_cards._schema
    tax = ResearchTaxonomyRepository(conn, schema=schema)
    tax.publish_version("test-v1", note="grain regression", activate=True)
    tax.define_chains(
        "test-v1",
        [
            {"domain": "optical", "chain": "Optical", "layer": "Semi", "layer_rank": 10},
            {"domain": "optical", "chain": "Optical", "layer": "Module", "layer_rank": 20},
        ],
    )
    # AVGO sits in BOTH layers — the exact shape that produced the defect.
    for layer, ticker in (
        ("Semi", "AVGO"),
        ("Module", "AVGO"),
        ("Module", "LITE"),
    ):
        tax.add_membership(
            "test-v1",
            chain="Optical",
            layer=layer,
            ticker=ticker,
            evidence_class="analyst",
            approved_by="test",
        )

    report = assemble_chain_report(
        conn, "Optical", schema=schema, as_of=date(2026, 8, 25), publish=False
    )
    by_kind = {b["block_kind"]: b["payload"] for b in report["blocks"]}
    assert by_kind["scope"]["members"] == 2
    assert by_kind["scope"]["member_placements"] == 3
    coverage = by_kind["chain_coverage"]
    assert coverage["members"] == 2
    assert coverage["with_compatible_result"] <= coverage["members"]
    # Two members, no dimensions: below the abstain floor and saying so.
    assert by_kind["chain_aggregate"]["abstains"] is True
    assert by_kind["chain_aggregate"]["priority_mean"] is None
    assert report["status"] == "partial"
