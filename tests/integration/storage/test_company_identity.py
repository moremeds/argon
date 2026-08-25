"""Historized issuer identity (migration 134).

`fundamental_company_type` is keyed on ticker alone, so a reclassification is an
UPDATE and the previous classification is gone. Every score computed under the
old type then reads as though it had been computed under the new one —
`fundamental_scores.inputs_hash` covers `company_type` precisely to stop that,
and the protection is worth nothing if the old value cannot be recovered.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from uw_scan.storage.company_identity import (
    STATUS_DEFAULTED,
    STATUS_EVIDENCED,
    STATUS_MANUAL,
    CompanyIdentityRepository,
)


def _repo(seeded) -> CompanyIdentityRepository:
    return CompanyIdentityRepository(seeded.conn, schema=seeded._schema)


def test_a_reclassification_opens_a_new_interval_and_closes_the_old(
    seeded_db_empty_cards,
):
    r = _repo(seeded_db_empty_cards)
    assert r.assign(
        "NVDA", company_type="chips_cyclical", status=STATUS_EVIDENCED,
        evidence="sector=Semi",
    )
    assert r.assign(
        "NVDA", company_type="platform_scale", status=STATUS_EVIDENCED,
        evidence="sector=M7",
    )

    hist = r.history("NVDA")
    assert [h["company_type"] for h in hist] == ["chips_cyclical", "platform_scale"]
    assert hist[0]["valid_to"] is not None, "the superseded interval must be closed"
    assert hist[1]["valid_to"] is None, "exactly one interval stays open"


def test_the_old_type_is_still_answerable_at_its_own_time(seeded_db_empty_cards):
    r = _repo(seeded_db_empty_cards)
    r.assign("NVDA", company_type="chips_cyclical", status=STATUS_EVIDENCED, evidence="a")
    r.assign("NVDA", company_type="platform_scale", status=STATUS_EVIDENCED, evidence="b")

    # Probe the recorded interval, not the wall clock: both assigns land within
    # the same second, so a now()-derived boundary lands before BOTH intervals
    # and would test nothing.
    old_iv, new_iv = r.history("NVDA")
    assert r.at("NVDA", old_iv["valid_from"])["company_type"] == "chips_cyclical"
    assert r.at("NVDA", new_iv["valid_from"])["company_type"] == "platform_scale"
    assert r.at("NVDA", datetime.now(UTC) + timedelta(hours=1))[
        "company_type"
    ] == "platform_scale"


def test_a_time_before_any_classification_returns_none_not_todays_type(
    seeded_db_empty_cards,
):
    """Falling back to the current type would date today's opinion in the past."""
    r = _repo(seeded_db_empty_cards)
    r.assign("NVDA", company_type="chips_cyclical", status=STATUS_EVIDENCED, evidence="a")
    assert r.at("NVDA", datetime(2001, 1, 1, tzinfo=UTC)) is None


def test_an_unchanged_reassignment_writes_no_interval(seeded_db_empty_cards):
    """A nightly reseed must cost nothing, or the history records only cron runs."""
    r = _repo(seeded_db_empty_cards)
    assert r.assign("NVDA", company_type="chips_cyclical", status=STATUS_EVIDENCED, evidence="a")
    assert not r.assign("NVDA", company_type="chips_cyclical", status=STATUS_EVIDENCED, evidence="a")
    assert len(r.history("NVDA")) == 1


def test_a_manual_override_survives_a_reseed(seeded_db_empty_cards):
    r = _repo(seeded_db_empty_cards)
    r.assign("PYPL", company_type="platform_scale", status=STATUS_MANUAL, evidence="human")
    assert not r.assign(
        "PYPL", company_type="financials", status=STATUS_EVIDENCED, evidence="sector=Fintech"
    )
    assert r.current("PYPL")["company_type"] == "platform_scale"


def test_two_open_intervals_are_refused_by_the_schema(seeded_db_empty_cards):
    """Two 'current' classifications make every as-of read non-deterministic."""
    seeded = seeded_db_empty_cards
    r = _repo(seeded)
    r.assign("NVDA", company_type="chips_cyclical", status=STATUS_EVIDENCED, evidence="a")
    with pytest.raises(psycopg.errors.UniqueViolation):
        with seeded.conn.cursor() as cur:
            cur.execute(
                f"""INSERT INTO {seeded._schema}.company_identity
                            (ticker, company_type, status, evidence)
                     VALUES ('NVDA', 'platform_scale', 'evidenced', 'b')"""
            )
    seeded.conn.rollback()


def test_coverage_separates_evidenced_from_defaulted(seeded_db_empty_cards):
    """Same company_type value, completely different epistemic standing."""
    seeded = seeded_db_empty_cards
    from uw_scan.storage.fundamental_obs import FundamentalObsRepository

    FundamentalObsRepository(seeded.conn, schema=seeded._schema).seed_universe(
        "ranked", [("NVDA", None, "t"), ("ABM", None, "t")]
    )
    r = _repo(seeded)
    r.assign("NVDA", company_type="chips_cyclical", status=STATUS_EVIDENCED, evidence="sector=Semi")
    r.assign("ABM", company_type="unclassified", status=STATUS_DEFAULTED, evidence="no sector")

    cov = r.coverage("ranked")
    assert cov == {
        "tier": "ranked",
        "names": 2,
        "classified": 2,
        "evidenced": 1,
        "defaulted": 1,
        "manual": 0,
        "unresolved": ["ABM"],
    }


def test_two_tickers_on_one_cik_are_reported_as_one_issuer(seeded_db_empty_cards):
    """GOOG/GOOGL file ONE set of financials; both in a cross-section double-counts."""
    r = _repo(seeded_db_empty_cards)
    for t in ("GOOG", "GOOGL"):
        r.assign(
            t, company_type="platform_scale", status=STATUS_EVIDENCED,
            evidence="sector=M7", issuer_cik="0001652044",
        )
    r.assign(
        "NVDA", company_type="chips_cyclical", status=STATUS_EVIDENCED,
        evidence="sector=Semi", issuer_cik="0001045810",
    )

    assert r.shared_issuers() == {"0001652044": ["GOOG", "GOOGL"]}
