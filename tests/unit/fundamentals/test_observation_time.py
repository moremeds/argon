"""Availability evidence vocabulary and admission policy (Pre-Job 0, task 1).

These tests exist because the words are the load-bearing part. `statement_panel`
was never wrong about SQL — it was wrong about what `obs_id DESC` MEANS, and a
serial primary key silently answered "which version is available at time T" with
"whichever we inserted last". Freezing the four classes and the two policies in
pure code, with no database in sight, is what stops the next reader from
inventing a fifth meaning halfway down a query.

The naive-datetime tests are not pedantry. A capture-bounded claim admits a
content version at or after a timestamp; comparing a naive datetime against an
aware cutoff raises in Python, and "assume UTC" would quietly shift a US filer's
availability by up to five hours across a cutoff boundary.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from uw_scan.fundamentals.observation_time import (
    CLAIM_KEY_CAPTURE_FIRST_OBSERVED,
    CLAIM_KEY_LEGACY_CURRENT_VINTAGE,
    EVIDENCE_CLASSES,
    EvidenceClass,
    EvidencePolicy,
    admits,
    audit_violations,
    claim_strength,
    normalize_claim,
    policy_classes,
)

AWARE = datetime(2021, 2, 3, 12, 0, tzinfo=UTC)
NAIVE = datetime(2021, 2, 3, 12, 0)


# --- the vocabulary is closed --------------------------------------------


def test_evidence_classes_are_exactly_the_four_agreed_names():
    assert {c.value for c in EVIDENCE_CLASSES} == {
        "true_pit",
        "capture_bounded",
        "current_vintage",
        "unknown",
    }


def test_an_unrecognised_class_is_refused_not_coerced():
    with pytest.raises(ValueError, match="evidence_class"):
        normalize_claim("probably_fine", AWARE)


# --- timestamp semantics per class ---------------------------------------


@pytest.mark.parametrize("cls", [EvidenceClass.TRUE_PIT, EvidenceClass.CAPTURE_BOUNDED])
def test_timed_classes_require_an_available_at(cls):
    with pytest.raises(ValueError, match="requires available_at"):
        normalize_claim(cls, None)


@pytest.mark.parametrize("cls", [EvidenceClass.TRUE_PIT, EvidenceClass.CAPTURE_BOUNDED])
def test_timed_classes_reject_a_naive_available_at(cls):
    with pytest.raises(ValueError, match="timezone-aware"):
        normalize_claim(cls, NAIVE)


@pytest.mark.parametrize("cls", [EvidenceClass.CURRENT_VINTAGE, EvidenceClass.UNKNOWN])
def test_untimed_classes_reject_an_available_at(cls):
    with pytest.raises(ValueError, match="must not carry available_at"):
        normalize_claim(cls, AWARE)


@pytest.mark.parametrize("cls", [EvidenceClass.CURRENT_VINTAGE, EvidenceClass.UNKNOWN])
def test_untimed_classes_normalize_to_a_null_timestamp(cls):
    assert normalize_claim(cls, None) == (cls, None)


def test_normalize_accepts_the_plain_string_form():
    assert normalize_claim("true_pit", AWARE) == (EvidenceClass.TRUE_PIT, AWARE)


def test_normalize_preserves_a_non_utc_offset_rather_than_shifting_it():
    eastern = datetime(2021, 2, 3, 7, 0, tzinfo=timezone(timedelta(hours=-5)))
    # A tz-aware value survives untouched; the contract is "aware", not "UTC".
    cls, at = normalize_claim(EvidenceClass.TRUE_PIT, eastern)
    assert at is eastern and cls is EvidenceClass.TRUE_PIT


# --- policy admission -----------------------------------------------------


def test_true_pit_only_admits_nothing_else():
    assert admits(EvidencePolicy.TRUE_PIT_ONLY, EvidenceClass.TRUE_PIT)
    for cls in (
        EvidenceClass.CAPTURE_BOUNDED,
        EvidenceClass.CURRENT_VINTAGE,
        EvidenceClass.UNKNOWN,
    ):
        assert not admits(EvidencePolicy.TRUE_PIT_ONLY, cls)


def test_capture_bounded_admits_the_two_timed_classes_only():
    assert admits(EvidencePolicy.CAPTURE_BOUNDED, EvidenceClass.TRUE_PIT)
    assert admits(EvidencePolicy.CAPTURE_BOUNDED, EvidenceClass.CAPTURE_BOUNDED)
    assert not admits(EvidencePolicy.CAPTURE_BOUNDED, EvidenceClass.CURRENT_VINTAGE)
    assert not admits(EvidencePolicy.CAPTURE_BOUNDED, EvidenceClass.UNKNOWN)


def test_no_historical_policy_admits_current_vintage_or_unknown():
    for policy in EvidencePolicy:
        admitted = policy_classes(policy)
        assert EvidenceClass.CURRENT_VINTAGE not in admitted
        assert EvidenceClass.UNKNOWN not in admitted


def test_policy_classes_are_immutable_to_callers():
    before = set(policy_classes(EvidencePolicy.CAPTURE_BOUNDED))
    with pytest.raises((AttributeError, TypeError)):
        policy_classes(EvidencePolicy.CAPTURE_BOUNDED).add(EvidenceClass.UNKNOWN)  # type: ignore[attr-defined]
    assert set(policy_classes(EvidencePolicy.CAPTURE_BOUNDED)) == before


# --- tie-breaking ---------------------------------------------------------


def test_true_pit_outranks_capture_bounded_at_the_same_instant():
    assert claim_strength(EvidenceClass.TRUE_PIT) > claim_strength(
        EvidenceClass.CAPTURE_BOUNDED
    )


def test_untimed_classes_rank_below_every_timed_class():
    for weak in (EvidenceClass.CURRENT_VINTAGE, EvidenceClass.UNKNOWN):
        assert claim_strength(weak) < claim_strength(EvidenceClass.CAPTURE_BOUNDED)


# --- deterministic replay keys -------------------------------------------


def test_rule_claim_keys_are_versioned_constants():
    # Rule identity, not row identity: replaying the same rule over the same
    # observation must collide on (obs_id, claim_key) and write nothing.
    assert CLAIM_KEY_CAPTURE_FIRST_OBSERVED != CLAIM_KEY_LEGACY_CURRENT_VINTAGE
    for key in (CLAIM_KEY_CAPTURE_FIRST_OBSERVED, CLAIM_KEY_LEGACY_CURRENT_VINTAGE):
        assert key.endswith(":v1"), "a rule change must move the key, not mutate rows"


# --- audit self-checks ----------------------------------------------------


def _clean_report() -> dict:
    return {
        "claims": 6,
        "by_evidence_class": {"capture_bounded": 3, "current_vintage": 3},
        "true_pit_without_evidence": 0,
        "untimed_claims_carrying_an_instant": 0,
        "unclaimed_observations": 0,
        "selection_check": [],
    }


def test_a_clean_report_passes():
    assert audit_violations(_clean_report()) == []


def test_counts_that_do_not_reconcile_fail():
    report = _clean_report() | {"claims": 7}
    assert any("sum to" in p for p in audit_violations(report))


def test_a_true_pit_claim_without_an_artifact_fails():
    report = _clean_report() | {"true_pit_without_evidence": 2}
    assert any("artifact reference" in p for p in audit_violations(report))


def test_an_untimed_class_carrying_an_instant_fails():
    report = _clean_report() | {"untimed_claims_carrying_an_instant": 1}
    assert any("make no availability claim" in p for p in audit_violations(report))


def test_an_unclassified_observation_fails():
    report = _clean_report() | {"unclaimed_observations": 12}
    assert any("no claim at all" in p for p in audit_violations(report))


def test_a_selection_past_its_cutoff_fails():
    report = _clean_report() | {
        "selection_check": [
            {
                "ticker": "NVDA",
                "period": "2020-03-31",
                "available_at": datetime(2024, 1, 1, tzinfo=UTC),
                "cutoff": datetime(2021, 1, 1, tzinfo=UTC),
            }
        ]
    }
    assert any("past its cutoff" in p for p in audit_violations(report))


def test_a_class_outside_the_vocabulary_fails():
    report = _clean_report() | {
        "by_evidence_class": {"capture_bounded": 3, "probably_fine": 3}
    }
    assert any("outside the vocabulary" in p for p in audit_violations(report))
