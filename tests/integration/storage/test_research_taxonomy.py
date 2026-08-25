"""Versioned taxonomy and exposure (migrations 137/138/139).

The load-bearing test is `test_an_asserted_exposure_cannot_carry_a_number`. On
the local store, 316 of 316 chain members have a role-level exposure and only 4
carry a disclosed magnitude — a 1.3% yield. Without the constraint those 312
rows would have been filled with plausible hand-typed percentages, and every
chain aggregate built on top would have inherited the fiction with no way to
detect it.
"""

from __future__ import annotations

import psycopg
import pytest

from uw_scan.storage.research_taxonomy import ResearchTaxonomyRepository

VERSION = "test-v1"


def _repo(seeded) -> ResearchTaxonomyRepository:
    r = ResearchTaxonomyRepository(seeded.conn, schema=seeded._schema)
    r.publish_version(VERSION, note="test", activate=True)
    r.define_chains(
        VERSION,
        [
            {"domain": "d", "chain": "Optical", "layer": "Module", "layer_rank": 30},
            {"domain": "d", "chain": "Optical", "layer": "Systems", "layer_rank": 40},
        ],
    )
    return r


def _exposure(**over):
    base = {
        "taxonomy_version": VERSION,
        "ticker": "COHR",
        "chain": "Optical",
        "role": "component",
        "magnitude_basis": "qualitative",
        "confidence": "low",
        "status": "asserted",
        "source_kind": "chain_membership",
    }
    base.update(over)
    return base


def test_an_asserted_exposure_cannot_carry_a_number(seeded_db_empty_cards):
    """No hand-authored percentage may masquerade as measured exposure."""
    r = _repo(seeded_db_empty_cards)
    with pytest.raises(ValueError, match="magnitude requires"):
        r.record_exposure([_exposure(magnitude=0.38)])


def test_the_database_refuses_it_too_not_only_the_repository(seeded_db_empty_cards):
    """Belt and braces: a caller bypassing the repository must still fail."""
    seeded = seeded_db_empty_cards
    _repo(seeded)
    with pytest.raises(psycopg.errors.CheckViolation):
        with seeded.conn.cursor() as cur:
            cur.execute(
                f"""INSERT INTO {seeded._schema}.company_exposure
                            (taxonomy_version, ticker, chain, role, magnitude,
                             magnitude_basis, confidence, status, source_kind)
                     VALUES (%s,'COHR','Optical','component', 0.38,
                             'qualitative','low','asserted','manual')""",
                (VERSION,),
            )
    seeded.conn.rollback()


def test_a_disclosed_segment_share_may_carry_a_number(seeded_db_empty_cards):
    r = _repo(seeded_db_empty_cards)
    assert (
        r.record_exposure(
            [
                _exposure(
                    magnitude=0.676,
                    magnitude_basis="segment_share",
                    status="disclosed",
                    confidence="high",
                    source_kind="revenue_breakdown_obs",
                    source_ref="avgo:SemiconductorSolutionsMember",
                )
            ]
        )
        == 1
    )
    got = r.exposures(VERSION, chain="Optical")[0]
    assert float(got["magnitude"]) == 0.676
    # The attribution is auditable too: the row names the member it came from.
    assert got["source_ref"] == "avgo:SemiconductorSolutionsMember"


def test_a_share_outside_zero_to_one_is_refused(seeded_db_empty_cards):
    """A column accepting both 0.38 and 38 gets both."""
    seeded = seeded_db_empty_cards
    _repo(seeded)
    with pytest.raises(psycopg.errors.CheckViolation):
        with seeded.conn.cursor() as cur:
            cur.execute(
                f"""INSERT INTO {seeded._schema}.company_exposure
                            (taxonomy_version, ticker, chain, role, magnitude,
                             magnitude_basis, confidence, status, source_kind)
                     VALUES (%s,'AVGO','Optical','component', 38,
                             'segment_share','high','disclosed','x')""",
                (VERSION,),
            )
    seeded.conn.rollback()


def test_membership_is_versioned_and_intervalled(seeded_db_empty_cards):
    r = _repo(seeded_db_empty_cards)
    assert r.add_membership(
        VERSION, chain="Optical", layer="Module", ticker="COHR",
        evidence_class="analyst", approved_by="tester",
    )
    # A reseed must not manufacture a history of identical intervals.
    assert not r.add_membership(
        VERSION, chain="Optical", layer="Module", ticker="COHR",
        evidence_class="analyst", approved_by="tester",
    )
    assert [m["ticker"] for m in r.members(VERSION, "Optical")] == ["COHR"]


def test_membership_must_name_a_layer_that_exists(seeded_db_empty_cards):
    """A member in an undeclared layer would be invisible in the matrix."""
    seeded = seeded_db_empty_cards
    r = _repo(seeded)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        r.add_membership(
            VERSION, chain="Optical", layer="NotALayer", ticker="COHR",
            evidence_class="analyst", approved_by="tester",
        )
    seeded.conn.rollback()


def test_only_one_taxonomy_version_can_be_active(seeded_db_empty_cards):
    r = _repo(seeded_db_empty_cards)
    r.publish_version("test-v2", activate=True)
    assert r.active_version() == "test-v2"


def test_coverage_reports_three_denominators(seeded_db_empty_cards):
    """members / with_exposure / with_magnitude answer different questions."""
    r = _repo(seeded_db_empty_cards)
    for t in ("COHR", "LITE"):
        r.add_membership(
            VERSION, chain="Optical", layer="Module", ticker=t,
            evidence_class="analyst", approved_by="tester",
        )
    r.record_exposure([_exposure(ticker="COHR")])
    r.record_exposure(
        [
            _exposure(
                ticker="LITE", magnitude=0.4, magnitude_basis="segment_share",
                status="disclosed", confidence="high", source_kind="obs",
            )
        ]
    )
    cov = r.exposure_coverage(VERSION)["Optical"]
    assert cov == {"members": 2, "with_exposure": 2, "with_magnitude": 1}


def test_the_matrix_carries_its_own_denominator(seeded_db_empty_cards):
    """A declared layer with no members must appear, hatched, not vanish."""
    r = _repo(seeded_db_empty_cards)
    r.add_membership(
        VERSION, chain="Optical", layer="Module", ticker="COHR",
        evidence_class="analyst", approved_by="tester",
    )
    matrix = {(m["chain"], m["layer"]): m["members"] for m in r.membership_matrix(VERSION)}
    assert matrix[("Optical", "Module")] == 1
    assert matrix[("Optical", "Systems")] == 0
