"""Golden-scenario tests for the USD transmission state.

Every input is real, frozen from the live publisher in
``tests/fixtures/macro/usd_gold_golden.json`` before this engine existed.  The ``expect``
blocks in that file are preregistered predictions: a test here that disagrees with one
is a finding about the engine, and the fixture is not the thing to edit.

Generator: ``scripts/research/build_usd_gold_golden.py``.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from uw_scan.macro.contracts import DomainObservation
from uw_scan.macro.usd import (
    ANCHOR_SERIES,
    REAL_SERIES,
    UpstreamState,
    compute_usd_state,
)

GOLDEN = json.loads(
    (
        Path(__file__).parents[2] / "fixtures" / "macro" / "usd_gold_golden.json"
    ).read_text(encoding="utf-8")
)
SCENARIOS: dict[str, dict[str, Any]] = {s["id"]: s for s in GOLDEN["scenarios"]}


def _observation(row: dict[str, Any]) -> DomainObservation:
    return DomainObservation(
        series_id=row["series_id"],
        causal_role=row["causal_role"],
        period_end=date.fromisoformat(row["period_end"]),
        value=Decimal(row["value"]),
        unit=row["unit"],
        publisher_transform="index_level",
        available_at=_instant(row["available_at"]),
        superseded_at=(
            _instant(row["superseded_at"]) if row.get("superseded_at") else None
        ),
        source=row["source"],
        source_kind=row["source_kind"],
        cost_class=row["cost_class"],
    )


def _instant(day: str) -> datetime:
    return datetime.fromisoformat(day).replace(tzinfo=UTC)


def _as_of(scenario_id: str, index: int = 0) -> datetime:
    """The scenario's own as_of, never a hardcoded one.

    Scenario 1's as_of moved from 2024-12-31 to 2025-01-08 once the fixture stopped
    collapsing vintages: the H.10 releases weekly in arrears, so an as_of equal to the
    last observation date cannot see it. A test carrying its own copy would have gone
    on passing against a window it no longer described.
    """
    raw = SCENARIOS[scenario_id]["as_of"]
    return _instant(raw[index] if isinstance(raw, list) else raw)


def _owned(scenario_id: str) -> tuple[DomainObservation, ...]:
    """Only the rows USD owns. The upstream-tagged rows are the point of test 1."""
    return tuple(
        _observation(row)
        for row in SCENARIOS[scenario_id]["inputs"]
        if row["owned_by"] == "usd"
    )


def _upstream(**kw: Any) -> UpstreamState:
    return UpstreamState(
        domain=kw.pop("domain", "policy_rates"),
        state=kw.pop("state", "EASING"),
        direction=kw.pop("direction", "FALLING"),
        inputs_hash=kw.pop("inputs_hash", "0" * 64),
        as_of=kw.pop("as_of", datetime(2024, 12, 31, tzinfo=UTC)),
        confidence=kw.pop("confidence", Decimal("1.0")),
    )


class TestDollarStrengthAgainstEasingPolicy:
    """Golden scenario 1. 2024-09-16..12-31: the dollar +6.4% through three cuts."""

    SCENARIO = "usd_strength_against_easing_policy"

    def _state(self, **kw: Any):
        return compute_usd_state(
            _owned(self.SCENARIO),
            as_of=_as_of(self.SCENARIO),
            upstream=(_upstream(),),
            **kw,
        )

    def test_the_state_is_what_the_anchor_did(self) -> None:
        assert self._state().state == "STRENGTHENING"
        assert self._state().direction == "RISING"

    def test_the_contradiction_fires(self) -> None:
        assert self._state().fired("usd_against_relative_policy")

    def test_the_contradiction_does_not_soften_the_state(self) -> None:
        """A disagreement is reported beside the state, never folded into it.

        A composite would have hedged this into INDETERMINATE and thrown away both
        facts: the dollar did rise, and the committee did cut.
        """
        assert self._state().state == "STRENGTHENING"

    def test_no_direction_is_inferred_for_policy(self) -> None:
        detail = self._state().contradictions[0].detail
        assert "No direction is inferred for either side" in detail

    def test_the_contradiction_admits_only_the_us_leg_is_observed(self) -> None:
        """The rule name says 'relative'; this desk ingests no foreign policy path.

        The frozen name cannot change without breaking the preregistration, so the
        limit is stated in the detail an operator actually reads.
        """
        assert (
            "not a measured rate differential" in self._state().contradictions[0].detail
        )

    def test_agreement_produces_no_contradiction(self) -> None:
        tightening = _upstream(state="TIGHTENING", direction="RISING")
        state = compute_usd_state(
            _owned(self.SCENARIO),
            as_of=_as_of(self.SCENARIO),
            upstream=(tightening,),
        )
        assert not state.contradictions

    def test_the_upstream_answer_is_referenced_by_identity(self) -> None:
        reason = self._state().reason("upstream_policy_rates")
        assert reason is not None
        assert reason.kind == "informational"
        assert "rather than recomputed from its inputs" in reason.detail

    def test_the_upstream_state_moves_the_inputs_hash(self) -> None:
        """A rates state that changed its mind must change USD's identity.

        Otherwise a USD state built on a revised upstream answer is indistinguishable
        from one built on the answer it replaced.
        """
        other = _upstream(inputs_hash="1" * 64)
        moved = compute_usd_state(
            _owned(self.SCENARIO),
            as_of=_as_of(self.SCENARIO),
            upstream=(other,),
        )
        assert moved.inputs_hash != self._state().inputs_hash


class TestAnchorAbsentStateAbstains:
    """Golden scenario 4. The substitute is present, plausible, and declined."""

    SCENARIO = "usd_anchor_absent_state_abstains"
    AS_OF = _as_of("usd_anchor_absent_state_abstains")

    def _state(self):
        return compute_usd_state(_owned(self.SCENARIO), as_of=self.AS_OF)

    def test_the_fixture_really_has_the_anchor_and_it_really_is_unavailable(
        self,
    ) -> None:
        # Guards the test itself: an empty anchor leg would make everything below pass
        # while proving nothing.
        rows = [r for r in _owned(self.SCENARIO) if r.series_id == ANCHOR_SERIES]
        assert rows, "fixture must carry anchor rows"
        assert not [r for r in rows if r.is_known_on(self.AS_OF)]

    def test_the_state_abstains(self) -> None:
        assert self._state().state == "UNKNOWN"
        assert self._state().direction == "UNKNOWN"

    def test_the_real_index_is_available_at_this_as_of(self) -> None:
        real = [
            r
            for r in _owned(self.SCENARIO)
            if r.series_id == REAL_SERIES and r.is_known_on(self.AS_OF)
        ]
        assert len(real) >= 12

    def test_the_real_index_is_not_promoted_to_anchor(self) -> None:
        state = self._state()
        assert state.state == "UNKNOWN"
        assert state.factor(ANCHOR_SERIES) is None
        # It is still REPORTED -- refusing to substitute is not refusing to look.
        assert state.factor(REAL_SERIES) is not None

    def test_the_refusal_is_recorded_as_a_decision_not_a_gap(self) -> None:
        reason = self._state().reason("real_index_not_substituted")
        assert reason is not None
        assert reason.kind == "informational"
        assert "was not promoted to anchor" in reason.detail

    def test_the_absence_reason_names_the_two_questions(self) -> None:
        reason = self._state().reason("required_period_absent_at_as_of")
        assert reason is not None
        assert "inflation differential" in reason.detail

    def test_confidence_is_zero_without_the_required_anchor(self) -> None:
        assert self._state().confidence == Decimal(0)


class TestBroadDollarRevisedAfterTheFact:
    """Golden scenario 5. Period 2026-08-03 restated 1.08 index points a week later."""

    SCENARIO = "broad_dollar_revised_after_the_fact"

    def _rows(self):
        return _owned(self.SCENARIO)

    @pytest.mark.parametrize(
        ("as_of", "expected"),
        [("2026-08-12", "120.7739000000"), ("2026-08-20", "119.6951000000")],
    )
    def test_the_replay_reads_the_vintage_in_force(
        self, as_of: str, expected: str
    ) -> None:
        stamp = _instant(as_of)
        visible = [
            row
            for row in self._rows()
            if row.series_id == ANCHOR_SERIES
            and row.period_end == date(2026, 8, 3)
            and row.is_known_on(stamp)
        ]
        assert len(visible) == 1, "exactly one vintage is in force at any instant"
        assert visible[0].value == Decimal(expected)

    def test_the_two_vintages_are_a_material_revision(self) -> None:
        """1.08 index points, silently, seven days after publication.

        Recorded because the size is the argument: it is roughly a tenth of the whole
        2024 dollar rally, which is not a rounding artifact.
        """
        values = {
            row.value for row in self._rows() if row.period_end == date(2026, 8, 3)
        }
        assert len(values) == 2
        assert abs(max(values) - min(values)) > Decimal("1")

    def test_a_replay_before_first_publication_sees_nothing(self) -> None:
        early = _instant("2026-08-09")
        assert not [row for row in self._rows() if row.is_known_on(early)]


class TestTheDoubleCountProhibition:
    """USD consumes upstream ANSWERS. Passing it upstream INPUTS is an error."""

    def test_an_upstream_role_passed_as_evidence_is_refused(self) -> None:
        rows = tuple(
            _observation(row)
            for row in SCENARIOS["usd_strength_against_easing_policy"]["inputs"]
        )
        with pytest.raises(ValueError, match="double-count"):
            compute_usd_state(rows, as_of=_as_of("usd_strength_against_easing_policy"))

    def test_the_refusal_names_the_offending_series(self) -> None:
        rows = tuple(
            _observation(row)
            for row in SCENARIOS["usd_strength_against_easing_policy"]["inputs"]
        )
        with pytest.raises(ValueError, match="EFFR"):
            compute_usd_state(rows, as_of=_as_of("usd_strength_against_easing_policy"))

    def test_the_owned_rows_alone_are_accepted(self) -> None:
        assert compute_usd_state(
            _owned("usd_strength_against_easing_policy"),
            as_of=_as_of("usd_strength_against_easing_policy"),
        )

    def test_only_owned_series_reach_the_evidence_refs(self) -> None:
        state = compute_usd_state(
            _owned("usd_strength_against_easing_policy"),
            as_of=_as_of("usd_strength_against_easing_policy"),
        )
        assert {ref.series_id for ref in state.evidence_refs} <= {
            ANCHOR_SERIES,
            REAL_SERIES,
        }


class TestMomentumWindow:
    def test_a_short_history_produces_no_change_rather_than_a_short_one(self) -> None:
        """A 6-observation 'quarterly' move is a different statistic, same label."""
        rows = _owned("broad_dollar_revised_after_the_fact")
        state = compute_usd_state(rows, as_of=_instant("2026-08-20"))
        assert state.state == "UNKNOWN"
        velocity = next(v for v in state.velocity if v.metric == "broad_dollar_change")
        assert velocity.value is None
        assert "different statistic" in velocity.unavailable_reason

    def test_the_threshold_is_the_measured_median_move(self) -> None:
        """Calibration, asserted so a later edit has to argue with the measurement.

        Across 5,169 observations from 2006-01-02 to 2026-08-14 the median absolute
        63-observation change is 1.81% and this threshold leaves 53.8% of days
        RANGEBOUND. A number chosen for feel would drift; this one has a reproduce
        command behind it.
        """
        from uw_scan.macro.usd import DEFAULT_USD_PARAMETERS

        assert DEFAULT_USD_PARAMETERS.momentum_threshold_pct == Decimal("2.0")
        assert DEFAULT_USD_PARAMETERS.momentum_window_obs == 63

    def test_the_anchor_cadence_is_weekly_not_daily(self) -> None:
        """The anchor is REQUIRED, so a wrong cadence deletes the state four days in five."""
        from uw_scan.macro.usd import DEFAULT_USD_PARAMETERS

        assert DEFAULT_USD_PARAMETERS.anchor_cadence_days == 7
