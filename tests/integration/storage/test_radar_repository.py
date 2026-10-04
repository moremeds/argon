"""ResearchRadarRepository against the radar golden's seed (I-35).

Expected values are the ones the committed ``golden/radar_gets.json`` records
for the corresponding API responses, read here at the repository boundary.
"""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal

import pytest

from tests.integration.api.test_radar_golden import ENGINE_A, ENGINE_B, TAX_V1, seed
from uw_scan.storage.radar import ResearchRadarRepository

pytestmark = pytest.mark.integration

NEW = _dt.date(2026, 6, 15)


@pytest.fixture
def radar(seeded_db_empty_cards) -> ResearchRadarRepository:
    seed(seeded_db_empty_cards)
    return ResearchRadarRepository(
        seeded_db_empty_cards.conn, schema=seeded_db_empty_cards._schema
    )


def test_has_statements(radar):
    # golden: STM -> no_compatible_run, XYZ -> no_coverage, aaa upper-cased.
    assert radar.has_statements("STM") is True
    assert radar.has_statements("aaa") is True
    assert radar.has_statements("XYZ") is False


def test_tier_size(radar):
    # golden radar scope.names per tier.
    assert radar.tier_size("ranked") == 6
    assert radar.tier_size("watch") == 3
    assert radar.tier_size("dormant") == 1
    assert radar.tier_size("no-such-tier") == 0


def test_latest_tier_dimensions(radar):
    rows = radar.latest_tier_dimensions("ranked", ENGINE_A)
    # ordered by ticker, dimension; one row per (ticker, dimension).
    keys = [(r[0], r[1]) for r in rows]
    assert keys == sorted(keys) and len(keys) == len(set(keys))
    assert sorted({r[0] for r in rows}) == ["AAA", "BBB", "CCC", "DDD", "EEE"]
    by_key = {(r[0], r[1]): r for r in rows}
    # golden: AAA priority 1.5 (newest, not 0.9), as_of 2026-06-15, compounder.
    aaa = by_key[("AAA", "priority")]
    assert aaa[2] == Decimal("1.5") and aaa[7] == NEW and aaa[8] == "compounder"
    # golden: BBB priority 0.4 (newest, not 2.0).
    assert by_key[("BBB", "priority")][2] == Decimal("0.4")
    # golden engine_b radar: only AAA, priority -0.2.
    b_rows = radar.latest_tier_dimensions("ranked", ENGINE_B)
    assert {r[0] for r in b_rows} == {"AAA"}
    assert {(r[1], r[2]) for r in b_rows if r[1] == "priority"} == {
        ("priority", Decimal("-0.2"))
    }


def test_chain_matrix_cells(radar):
    rows = radar.chain_matrix_cells(ENGINE_A, TAX_V1, None)
    # golden matrix cells (domain, chain, layer, layer_rank, members,
    # with_result, with_magnitude) in order.
    assert [(r[0], r[1], r[2], r[3], r[4], r[5], r[7]) for r in rows] == [
        ("ai", "Compute", "Accelerator", 10, 4, 4, 1),
        ("ai", "Optical", "Laser", 20, 0, 0, 0),
        ("ai", "Optical", "Module", 30, 4, 4, 1),
        ("ai", "Optical", "Systems", 40, 2, 1, 0),
        ("energy", "Power", "Grid", 10, 0, 0, 0),
    ]
    # golden priority_mean of the two non-abstaining cells.
    assert float(rows[0][6]) == pytest.approx(1.1)
    assert float(rows[2][6]) == pytest.approx(0.766666667)
    energy = radar.chain_matrix_cells(ENGINE_A, TAX_V1, "energy")
    assert [(r[0], r[1], r[2]) for r in energy] == [("energy", "Power", "Grid")]


def test_chain_member_rows(radar):
    rows = radar.chain_member_rows(ENGINE_A, TAX_V1, "Optical", "Systems")
    assert rows == [
        ("DDD", "Systems", "analyst", "golden-operator",
         None, None, None, None, None, None, None),
        ("FFF", "Systems", "analyst", "golden-operator",
         None, None, None, None, None, None, Decimal("-0.6")),
    ]  # fmt: skip
    # golden Optical (all layers): AAA's disclosed exposure and priority 1.5.
    all_rows = radar.chain_member_rows(ENGINE_A, TAX_V1, "Optical", None)
    assert [r[0] for r in all_rows] == ["AAA", "BBB", "CCC", "EEE", "DDD", "FFF"]
    assert all_rows[0][4:] == (
        "component", "upstream", Decimal("0.4"), "segment_share",
        "disclosed", "aaa:OpticsMember", Decimal("1.5"),
    )  # fmt: skip
    assert radar.chain_member_rows(ENGINE_A, TAX_V1, "NoSuchChain", None) == []
