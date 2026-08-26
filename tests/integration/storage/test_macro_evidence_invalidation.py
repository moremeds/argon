"""The overlay that lets the ledger say "we accepted this and were wrong" (migration 131).

``macro_observations`` is immutable -- migration 115's guard rejects every DELETE and every
UPDATE touching anything but ``last_seen_at`` -- so ``quality_status`` cannot be moved to
``quarantined`` after the fact. These tests fix the one property that makes an additive
overlay honest instead of a soft delete: the invalidation carries its OWN point-in-time
clock, so a replay of an instant before we discovered the problem still returns the row
Argon genuinely believed, and a read after it does not.

The fixture is the real FRED rebasing, frozen from
``docs/research/2026-08-21-rates-market-layer-probe/VERDICT.md``: ``WRESBAL`` period
2025-06-04 carries ``3294.381`` at vintage 2025-06-05 and ``3294381.0`` at vintage
2025-11-13, both labelled ``millions_usd``. Ratio exactly 1000.0, across 566 periods.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from uw_scan.macro_evidence import (
    macro_artifact_content_identity,
    macro_observation_content_hash,
)
from uw_scan.storage.repository import Repository

SERIES = "WRESBAL"

#: A period we hold at BOTH vintages. Used where the point is which of two rows survives.
PERIOD = date(2025, 6, 4)

#: A period we hold ONLY at the pre-rebasing vintage -- 566 of them were rebased and there
#: is no guarantee we captured a post row for each. This is the period the clock tests use,
#: because it is the only shape where the two failure modes are distinguishable: with both
#: vintages present the post row wins on ``available_at DESC`` regardless of the overlay, so
#: a test asserting "the post value came back" would pass with the feature deleted.
PERIOD_ONLY_PRE = date(2025, 5, 28)

#: The pre-rebasing publication and the value it carried.
PRE_VINTAGE = datetime(2025, 6, 5, 16, 30, tzinfo=UTC)
PRE_VALUE = Decimal("3294.381")

#: The republish that multiplied 566 periods of history by exactly 1000 without changing
#: the declared unit. Both rows say ``millions_usd``; only one of them can be right.
POST_VINTAGE = datetime(2025, 11, 13, 16, 30, tzinfo=UTC)
POST_VALUE = Decimal("3294381.0")

#: When WE found out. Deliberately later than the republish: the overlay's clock is the
#: discovery, never the publisher's error.
DISCOVERED = datetime(2026, 8, 24, 12, tzinfo=UTC)

SOURCES = ("FRED",)


@pytest.fixture
def repo(seeded_db_empty_cards) -> Repository:
    return seeded_db_empty_cards


def _artifact(repo: Repository, *, record_id: str, available_at: datetime) -> int:
    raw = {"series": SERIES, "record": record_id}
    content_hash, length = macro_artifact_content_identity(raw_json=raw)
    return repo.insert_macro_artifact(
        source="FRED",
        source_kind="official",
        source_record_id=record_id,
        source_url="https://fred.stlouisfed.org/series/WRESBAL",
        published_at=available_at,
        available_at=available_at,
        retrieved_at=available_at,
        content_hash=content_hash,
        parser_version="fred-v1",
        quality_status="valid",
        cost_class="free_official",
        media_type="application/json",
        content_length=length,
        vintage_bearing=False,
        raw_json=raw,
    )


def _observe(
    repo: Repository,
    *,
    artifact_id: int,
    record_id: str,
    available_at: datetime,
    value: Decimal,
    period_end: date = PERIOD,
) -> None:
    row: dict[str, Any] = {
        "artifact_id": artifact_id,
        "domain": "policy_rates",
        "series_id": SERIES,
        "period_end": period_end,
        "frequency": "weekly",
        "unit": "millions_usd",
        "value_numeric": value,
        "value_text": None,
        "value_json": None,
        "source": "FRED",
        "source_record_id": record_id,
        "published_at": available_at,
        "available_at": available_at,
        "parser_version": "fred-v1",
        "quality_status": "valid",
        "cost_class": "free_official",
    }
    row["content_hash"] = macro_observation_content_hash(row)
    repo.insert_macro_observations([row], seen_at=available_at)


def _seed_both_vintages(repo: Repository) -> None:
    _observe(
        repo,
        artifact_id=_artifact(repo, record_id="wresbal-pre", available_at=PRE_VINTAGE),
        record_id="wresbal-pre",
        available_at=PRE_VINTAGE,
        value=PRE_VALUE,
    )
    _observe(
        repo,
        artifact_id=_artifact(repo, record_id="wresbal-post", available_at=POST_VINTAGE),
        record_id="wresbal-post",
        available_at=POST_VINTAGE,
        value=POST_VALUE,
    )


def _invalidate_pre_rebase(repo: Repository, *, at: datetime = DISCOVERED) -> int:
    """Every vintage of WRESBAL up to the last pre-rebasing publication, no lower bound.

    ``vintage_to`` is INCLUSIVE -- the same shape as ``available_at <= as_of`` -- so it
    names the last bad vintage rather than the instant the good one arrived. Passing
    ``POST_VINTAGE`` here would condemn the republish itself, which is the row that fixed
    the problem.
    """
    return repo.insert_macro_evidence_invalidation(
        target_kind="series_range",
        series_id=SERIES,
        vintage_to=PRE_VINTAGE,
        invalidated_at=at,
        reason=(
            "FRED republished 566 periods multiplied by 1000 on 2025-11-13 while the "
            "contract still labels every vintage millions_usd"
        ),
        evidence_url="https://fred.stlouisfed.org/series/WRESBAL",
        reviewer="operator",
        overlay_version="wresbal-rebase/1",
    )


def _seed_only_pre_vintage(repo: Repository) -> None:
    _observe(
        repo,
        artifact_id=_artifact(repo, record_id="wresbal-pre-only", available_at=PRE_VINTAGE),
        record_id="wresbal-pre-only",
        available_at=PRE_VINTAGE,
        value=PRE_VALUE,
        period_end=PERIOD_ONLY_PRE,
    )


def _value_at(
    repo: Repository, as_of: datetime, *, period: date = PERIOD
) -> Decimal | None:
    row = repo.fetch_macro_observation_as_of(
        SERIES, period, as_of, preferred_sources=SOURCES
    )
    return None if row is None else row["value_numeric"]


class TestTheOverlayHasItsOwnClock:
    """The period held only at its pre-rebasing vintage, so exclusion is visible.

    Each test below names the production change that breaks it. A test that passes with
    the predicate deleted is not testing the predicate.
    """

    def test_a_replay_before_the_discovery_still_believes_the_bad_row(
        self, repo: Repository
    ) -> None:
        # Breaks if the predicate drops `invalidated_at <= as_of` and filters
        # unconditionally. In June 2025 Argon genuinely stood on 3294.381; a replay that
        # hid it would make the record a fiction rather than a point-in-time answer.
        _seed_only_pre_vintage(repo)
        _invalidate_pre_rebase(repo)

        assert _value_at(repo, PRE_VINTAGE, period=PERIOD_ONLY_PRE) == PRE_VALUE

    def test_a_read_after_the_discovery_excludes_it(self, repo: Repository) -> None:
        # Breaks if the predicate is missing entirely.
        _seed_only_pre_vintage(repo)
        _invalidate_pre_rebase(repo)

        assert _value_at(repo, DISCOVERED, period=PERIOD_ONLY_PRE) is None

    def test_the_boundary_is_the_discovery_instant_not_the_publishers_error(
        self, repo: Repository
    ) -> None:
        # Breaks if the overlay is keyed on the republish date instead of ours: every
        # replay between 2025-11-13 and 2026-08-24 would stop returning a row Argon
        # believed for those nine months.
        _seed_only_pre_vintage(repo)
        _invalidate_pre_rebase(repo)

        one_second_before = DISCOVERED - timedelta(seconds=1)
        assert _value_at(repo, one_second_before, period=PERIOD_ONLY_PRE) == PRE_VALUE
        assert _value_at(repo, DISCOVERED, period=PERIOD_ONLY_PRE) is None

    def test_an_unrelated_series_is_untouched(self, repo: Repository) -> None:
        # Breaks if the series_range arm forgets `v.series_id = o.series_id` -- a NULL
        # series_id on an observation-target row would otherwise match everything.
        _seed_both_vintages(repo)
        repo.insert_macro_evidence_invalidation(
            target_kind="observation",
            obs_id=next(
                r["obs_id"]
                for r in repo.fetch_macro_observation_history(SERIES, PERIOD)
                if r["value_numeric"] == PRE_VALUE
            ),
            invalidated_at=DISCOVERED,
            reason="one row only",
            reviewer="operator",
            overlay_version="single/1",
        )
        _seed_only_pre_vintage(repo)

        assert _value_at(repo, DISCOVERED, period=PERIOD_ONLY_PRE) == PRE_VALUE


class TestTheRangeArmBoundsWhatItSays:
    def test_an_open_lower_bound_takes_only_the_pre_rebasing_vintages(
        self, repo: Repository
    ) -> None:
        # Breaks if the predicate is missing: the series read returns both periods.
        _seed_both_vintages(repo)
        _seed_only_pre_vintage(repo)
        _invalidate_pre_rebase(repo)

        rows = repo.fetch_macro_series_as_of(SERIES, DISCOVERED, preferred_sources=SOURCES)
        assert [(r["period_end"], r["value_numeric"]) for r in rows] == [
            (PERIOD, POST_VALUE)
        ]

    def test_a_vintage_range_takes_the_publication(self, repo: Repository) -> None:
        # Pairs with the next test. vintage_* bounds `available_at`; period_* bounds
        # `period_end`. Swapping them in the predicate flips BOTH, which is why neither
        # assertion alone would catch it.
        _seed_only_pre_vintage(repo)
        repo.insert_macro_evidence_invalidation(
            target_kind="series_range",
            series_id=SERIES,
            vintage_from=PRE_VINTAGE,
            vintage_to=PRE_VINTAGE,
            invalidated_at=DISCOVERED,
            reason="the publication instant, which is what vintage_* means",
            reviewer="operator",
            overlay_version="bounds-check/1",
        )
        assert _value_at(repo, DISCOVERED, period=PERIOD_ONLY_PRE) is None

    def test_a_period_range_over_the_same_instants_matches_nothing(
        self, repo: Repository
    ) -> None:
        # Same numbers, read as PERIODS: 2025-05-28 is not inside 2025-06-05..2025-11-13.
        _seed_only_pre_vintage(repo)
        repo.insert_macro_evidence_invalidation(
            target_kind="series_range",
            series_id=SERIES,
            period_from=PRE_VINTAGE.date(),
            period_to=POST_VINTAGE.date(),
            invalidated_at=DISCOVERED,
            reason="period-bounded, must not match a period that precedes the range",
            reviewer="operator",
            overlay_version="bounds-check/1",
        )
        assert _value_at(repo, DISCOVERED, period=PERIOD_ONLY_PRE) == PRE_VALUE

    def test_a_period_range_covering_the_reading_takes_every_vintage_of_it(
        self, repo: Repository
    ) -> None:
        # Breaks if the predicate is missing: the post row would still answer.
        _seed_both_vintages(repo)
        repo.insert_macro_evidence_invalidation(
            target_kind="series_range",
            series_id=SERIES,
            period_from=PERIOD,
            period_to=PERIOD,
            invalidated_at=DISCOVERED,
            reason="the whole reading is unusable, at every vintage",
            reviewer="operator",
            overlay_version="bounds-check/1",
        )

        assert _value_at(repo, DISCOVERED) is None


class TestTheOtherStateFeedingReaders:
    def test_latest_observation_excludes_an_invalidated_row(
        self, repo: Repository
    ) -> None:
        # Only the pre vintage is held, so a working predicate leaves the series with no
        # answer at all. Breaks if this reader was left off the predicate.
        _seed_only_pre_vintage(repo)
        _invalidate_pre_rebase(repo)

        assert (
            repo.fetch_latest_macro_observation_as_of(
                SERIES, DISCOVERED, preferred_sources=SOURCES
            )
            is None
        )

    def test_recent_releases_exclude_an_invalidated_row(self, repo: Repository) -> None:
        # Seeded with the pre-vintage period alone, so the assertion is a row versus no
        # row. Breaks if this reader was left off the predicate.
        #
        # Not seeded with both periods on purpose: this reader is DISTINCT ON
        # (release_key), `insert_macro_observations` never writes that column, and
        # DISTINCT ON treats two NULLs as equal -- so a two-period fixture collapses to one
        # row and the test would pass with the predicate deleted.
        _seed_only_pre_vintage(repo)
        _invalidate_pre_rebase(repo)

        assert (
            repo.fetch_recent_macro_observations_as_of(
                SERIES, DISCOVERED, preferred_sources=SOURCES, limit=10
            )
            == []
        )

    def test_an_observation_target_takes_exactly_one_row(self, repo: Repository) -> None:
        # Invalidate the row that would otherwise WIN, so the fallback is observable.
        _seed_both_vintages(repo)
        post = next(
            r
            for r in repo.fetch_macro_observation_history(SERIES, PERIOD)
            if r["value_numeric"] == POST_VALUE
        )
        repo.insert_macro_evidence_invalidation(
            target_kind="observation",
            obs_id=post["obs_id"],
            invalidated_at=DISCOVERED,
            reason="this single row, nothing else",
            reviewer="operator",
            overlay_version="single/1",
        )

        assert _value_at(repo, DISCOVERED) == PRE_VALUE

    def test_an_artifact_target_takes_the_rows_parsed_out_of_it(
        self, repo: Repository
    ) -> None:
        _seed_both_vintages(repo)
        post = next(
            r
            for r in repo.fetch_macro_observation_history(SERIES, PERIOD)
            if r["value_numeric"] == POST_VALUE
        )
        repo.insert_macro_evidence_invalidation(
            target_kind="artifact",
            artifact_id=post["artifact_id"],
            invalidated_at=DISCOVERED,
            reason="the whole payload was misparsed",
            reviewer="operator",
            overlay_version="artifact/1",
        )

        assert _value_at(repo, DISCOVERED) == PRE_VALUE



class TestTheAuditViewMustNotFilterItself:
    def test_history_still_returns_an_invalidated_row(self, repo: Repository) -> None:
        # Filtering this view would answer "what did we discard and why" with a view that
        # had already discarded it.
        _seed_both_vintages(repo)
        _invalidate_pre_rebase(repo)

        values = {
            r["value_numeric"]
            for r in repo.fetch_macro_observation_history(SERIES, PERIOD)
        }
        assert values == {PRE_VALUE, POST_VALUE}

    def test_history_marks_the_invalidated_row_with_its_reason_and_reviewer(
        self, repo: Repository
    ) -> None:
        _seed_both_vintages(repo)
        _invalidate_pre_rebase(repo)

        rows = repo.fetch_macro_observation_history(SERIES, PERIOD)
        by_value = {r["value_numeric"]: r for r in rows}
        assert by_value[POST_VALUE]["invalidated_at"] is None
        assert by_value[POST_VALUE]["invalidation_reason"] is None
        assert by_value[PRE_VALUE]["invalidated_at"] == DISCOVERED
        assert "multiplied by 1000" in by_value[PRE_VALUE]["invalidation_reason"]
        assert by_value[PRE_VALUE]["invalidated_by"] == "operator"


class TestTheEvidenceItselfSurvives:
    def test_the_raw_artifact_is_byte_identical_after_invalidation(
        self, repo: Repository
    ) -> None:
        # Invalidation removes evidence from consideration. It never rewrites a value, and
        # it must never be a soft delete of the bytes.
        _seed_both_vintages(repo)
        history = repo.fetch_macro_observation_history(SERIES, PERIOD)
        pre = next(r for r in history if r["value_numeric"] == PRE_VALUE)
        before = repo.fetch_macro_artifact(pre["artifact_id"])

        _invalidate_pre_rebase(repo)

        after = repo.fetch_macro_artifact(pre["artifact_id"])
        assert after == before
        assert after["content_hash"] == before["content_hash"]

    def test_the_observation_row_keeps_its_quality_status(
        self, repo: Repository
    ) -> None:
        _seed_both_vintages(repo)
        _invalidate_pre_rebase(repo)

        pre = next(
            r
            for r in repo.fetch_macro_observation_history(SERIES, PERIOD)
            if r["value_numeric"] == PRE_VALUE
        )
        assert pre["quality_status"] == "valid"
