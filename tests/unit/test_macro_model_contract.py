"""Invariants the macro policy contract must hold before it reaches the API.

These are pure model tests: they exist so a malformed coverage report is
impossible to construct, not merely unlikely to be built.
"""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from uw_scan.models import (
    PolicyPathPoint,
    PolicyReleaseFailure,
    PolicySourceFreshness,
)


def _failure(
    release_key: str = "fomc-statement:monetary20200315a",
) -> PolicyReleaseFailure:
    return PolicyReleaseFailure(
        release_key=release_key,
        event_date=date(2020, 3, 15),
        error_type="uw_scan.normalize.NormalizationError",
        error_message="unreadable target range",
    )


def test_coverage_defaults_to_no_claim_rather_than_to_full_coverage():
    """An unpopulated report must not read as "everything succeeded"."""
    freshness = PolicySourceFreshness(source="federal_reserve_fomc", status="ok")

    assert freshness.releases_discovered == 0
    assert freshness.releases_succeeded == 0
    assert freshness.releases_failed == 0
    assert freshness.release_failures == []


def test_outcomes_cannot_exceed_the_releases_discovered():
    """Succeeded + failed > discovered means one of the three counts is a lie."""
    with pytest.raises(ValidationError, match="must account for every"):
        PolicySourceFreshness(
            source="federal_reserve_fomc",
            status="ok",
            releases_discovered=2,
            releases_succeeded=2,
            releases_failed=1,
        )


def test_release_counts_cannot_be_negative():
    with pytest.raises(ValidationError, match="cannot be negative"):
        PolicySourceFreshness(
            source="federal_reserve_fomc", status="ok", releases_failed=-1
        )


def test_detail_may_be_capped_but_never_invented():
    """Fewer details than failures is a cap; more is a fabricated failure."""
    capped = PolicySourceFreshness(
        source="federal_reserve_fomc",
        status="ok",
        releases_discovered=30,
        releases_succeeded=18,
        releases_failed=12,
        release_failures=[_failure()],
    )
    assert capped.releases_failed == 12

    with pytest.raises(ValidationError, match="cannot exceed the failure count"):
        PolicySourceFreshness(
            source="federal_reserve_fomc",
            status="ok",
            releases_discovered=2,
            releases_succeeded=1,
            releases_failed=1,
            release_failures=[_failure("a"), _failure("b")],
        )


def test_vote_status_distinguishes_unpublished_from_absent():
    """Three states, three meanings; the API must be able to say each one."""
    stated = PolicyPathPoint(
        horizon="current", rate_percent="4.375", vote_status="stated"
    )
    unpublished = PolicyPathPoint(
        horizon="current", rate_percent="4.375", vote_status="not_stated"
    )
    # A SEP projection has no vote at all -- not an unpublished one.
    projection = PolicyPathPoint(horizon="2026", rate_percent="3.4")

    assert (stated.vote_status, unpublished.vote_status, projection.vote_status) == (
        "stated",
        "not_stated",
        None,
    )


def test_vote_status_rejects_an_unmodelled_state():
    with pytest.raises(ValidationError):
        PolicyPathPoint(
            horizon="current", rate_percent="4.375", vote_status="unanimous"
        )


def test_a_release_outcome_cannot_go_uncounted() -> None:
    """Every discovered release is either a success or a hole, never neither.

    The catalog has four statuses, two of which produce no fact.  Leaving the
    counts merely "not exceeding" the total let ``artifact_only`` sit in a
    limbo that read as healthy; requiring equality makes that limbo
    unconstructible rather than merely unfixed.
    """
    with pytest.raises(ValidationError, match="must account for every"):
        PolicySourceFreshness(
            source="federal_reserve_fomc",
            status="ok",
            releases_discovered=20,
            releases_succeeded=17,
            releases_failed=0,
        )


def test_a_tally_without_a_roster_is_not_a_unanimous_committee() -> None:
    """The 9-3 case: three dissenters exist and the publisher named none.

    Two of 55 statements in the 2020+ archive print a tally with no roster.
    Without ``voter_names_stated`` the API hands a consumer an empty
    ``voted_against`` and no way to tell it apart from genuine unanimity --
    which reads a 9-3 as 12-0, in the direction that invents committee
    agreement that did not happen.
    """
    unnamed = PolicyPathPoint(
        horizon="current",
        rate_percent="4.375",
        vote_status="stated",
        vote_split="9-3",
        voter_names_stated=False,
    )
    unanimous = PolicyPathPoint(
        horizon="current",
        rate_percent="4.375",
        vote_status="stated",
        vote_split="12-0",
        voted_for=["Powell", "Jefferson"],
        voter_names_stated=True,
    )

    assert unnamed.voted_against == unanimous.voted_against == []
    # The empty roster alone cannot separate them; the flag is what does.
    assert unnamed.voter_names_stated is False
    assert unanimous.voter_names_stated is True


def test_a_dissent_roster_survives_the_api_model() -> None:
    """The composition is the signal; a tally cannot recover it.

    ``_UwBase`` ignores extra keys, so a field the model does not declare is
    dropped from the persisted JSON in silence rather than raising.
    """
    point = PolicyPathPoint.model_validate(
        {
            "horizon": "current",
            "rate_percent": "5.375",
            "vote_status": "stated",
            "vote_split": "11-1",
            "voted_for": ["Powell", "Williams"],
            "voted_against": ["Bowman"],
            "voter_names_stated": True,
        }
    )

    assert point.voted_against == ["Bowman"]
    assert point.voted_for == ["Powell", "Williams"]
