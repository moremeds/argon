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
    with pytest.raises(ValidationError, match="cannot exceed the releases discovered"):
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
        releases_failed=12,
        release_failures=[_failure()],
    )
    assert capped.releases_failed == 12

    with pytest.raises(ValidationError, match="cannot exceed the failure count"):
        PolicySourceFreshness(
            source="federal_reserve_fomc",
            status="ok",
            releases_discovered=2,
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
