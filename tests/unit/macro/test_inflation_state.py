"""The inflation engine, checked against preregistered golden scenarios.

The scenarios in ``tests/fixtures/macro/inflation_rates_golden.json`` were written
before this engine existed, from real vintage-stamped source data.  Their ``expect``
blocks are predictions: if one fails, the engine is wrong or the prediction was, and
either way the fixture is not the thing that gets edited.

Two of them already earned their keep before a line of engine code was written.
Scenario 1 originally predicted ``stickiness_not_confirming_disinflation``; sticky core
had in fact fallen 0.83pp over the window, confirming the disinflation, and the real
signature was a level divergence between headline and core.  Scenario 2 surfaced median
CPI at +0.89 against trimmed mean at -0.90 -- two breadth measures from one publisher
pointing opposite ways -- which no rule covered until it did.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from uw_scan.macro.confidence import compute_confidence
from uw_scan.macro.contracts import DomainObservation
from uw_scan.macro.inflation import (
    DEFAULT_INFLATION_PARAMETERS,
    REQUIRED,
    STATE_BASIS,
    InflationParameters,
    compute_inflation_state,
)
from uw_scan.macro.transforms import change_over_months, shift_months

FIXTURE = (
    Path(__file__).parents[2] / "fixtures" / "macro" / "inflation_rates_golden.json"
)
GOLDEN: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
SCENARIOS: dict[str, Any] = {row["id"]: row for row in GOLDEN["scenarios"]}

#: The fixture's derived column rounds each year-over-year to two decimals *before*
#: differencing them, so its three-month changes can sit one unit in the last place away
#: from a change differenced at full precision.  The engine differences first, which is
#: the more accurate order; 0.01pp is far below the 0.15pp direction threshold, so the
#: two conventions can never disagree about a label.
ROUNDING_ULP = Decimal("0.01")


def _instant(day: str) -> datetime:
    return datetime.combine(date.fromisoformat(day), datetime.min.time(), UTC)


def _observations(
    scenario_id: str, *, only: set[str] | None = None
) -> list[DomainObservation]:
    """Build engine inputs from the scenario's real, vintage-stamped history."""
    scenario = SCENARIOS[scenario_id]
    out: list[DomainObservation] = []
    for series_id, block in scenario["observation_history"].items():
        if only is not None and series_id not in only:
            continue
        role = REQUIRED[series_id][0]
        for row in block["observations"]:
            out.append(
                DomainObservation(
                    series_id=series_id,
                    causal_role=role,
                    period_end=date.fromisoformat(row["period_end"]),
                    value=Decimal(row["value"]),
                    unit=block["unit"],
                    publisher_transform=block["publisher_transform"],
                    available_at=_instant(row["available_at"]),
                    source="fred",
                    source_kind="first_party_publisher",
                    cost_class="free_publisher",
                )
            )
    return out


def _vintage_observations(scenario_id: str) -> list[DomainObservation]:
    """Scenario 6b: one period carrying every restatement it has ever had."""
    scenario = SCENARIOS[scenario_id]
    out: list[DomainObservation] = []
    for row in scenario["inputs"]:
        for vintage in row["vintages"]:
            superseded = vintage["superseded_at"]
            out.append(
                DomainObservation(
                    series_id=row["series_id"],
                    causal_role=row["causal_role"],
                    period_end=date.fromisoformat(row["period_end"]),
                    value=Decimal(vintage["value"]),
                    unit=row["unit"],
                    publisher_transform="index",
                    available_at=_instant(vintage["available_at"]),
                    # FRED's realtime_end is the last day the value was current,
                    # inclusive, so the half-open window closes the day after.
                    superseded_at=(
                        None
                        if superseded == "9999-12-31"
                        else _instant(superseded) + timedelta(days=1)
                    ),
                    source="fred",
                    source_kind="first_party_publisher",
                    cost_class="free_publisher",
                )
            )
    return out


def _state(scenario_id: str, **kwargs: Any):
    scenario = SCENARIOS[scenario_id]
    return compute_inflation_state(
        _observations(scenario_id),
        as_of=_instant(scenario["as_of"]),
        **kwargs,
    )


GOLDEN_INFLATION = ["disinflation_with_sticky_services", "broad_reacceleration"]


class TestPreregisteredScenarios:
    @pytest.mark.parametrize("scenario_id", GOLDEN_INFLATION)
    def test_state_and_direction_match_the_prediction(self, scenario_id: str) -> None:
        expect = SCENARIOS[scenario_id]["expect"]
        state = _state(scenario_id)
        assert state.state == expect["state"]
        assert state.direction == expect["direction"]

    @pytest.mark.parametrize("scenario_id", GOLDEN_INFLATION)
    def test_predicted_contradictions_fire(self, scenario_id: str) -> None:
        expect = SCENARIOS[scenario_id]["expect"]
        state = _state(scenario_id)
        fired = {item.rule for item in state.contradictions}
        assert set(expect["contradictions_include"]) <= fired, (
            f"expected {expect['contradictions_include']}, fired {sorted(fired)}"
        )

    @pytest.mark.parametrize("scenario_id", GOLDEN_INFLATION)
    def test_excluded_contradictions_stay_silent(self, scenario_id: str) -> None:
        expect = SCENARIOS[scenario_id]["expect"]
        state = _state(scenario_id)
        fired = {item.rule for item in state.contradictions}
        assert not set(expect["contradictions_exclude"]) & fired

    @pytest.mark.parametrize("scenario_id", GOLDEN_INFLATION)
    def test_confidence_lands_in_the_predicted_band(self, scenario_id: str) -> None:
        low, high = SCENARIOS[scenario_id]["expect"]["confidence_band"]
        state = _state(scenario_id)
        assert Decimal(str(low)) <= state.confidence <= Decimal(str(high)), (
            f"{state.confidence} outside [{low}, {high}]; terms: "
            + "; ".join(f"{r.term}={r.value}" for r in state.confidence_reasons)
        )

    @pytest.mark.parametrize("scenario_id", GOLDEN_INFLATION)
    def test_every_load_bearing_input_is_reconstructible(
        self, scenario_id: str
    ) -> None:
        state = _state(scenario_id)
        refs = {(ref.series_id, ref.period_end) for ref in state.evidence_refs}
        for factor in state.factors:
            assert (factor.series_id, factor.period_end) in refs


class TestTransformsAreComputedNotHandedOver:
    """The engine derives its own rates from index levels available at ``as_of``."""

    @pytest.mark.parametrize("scenario_id", GOLDEN_INFLATION)
    def test_core_pce_year_over_year_matches_the_frozen_measurement(
        self, scenario_id: str
    ) -> None:
        derived = SCENARIOS[scenario_id]["derived_from_inputs"]
        state = _state(scenario_id)
        basis = state.factor(STATE_BASIS)
        assert basis is not None
        # The engine reports the index level; the rate it derived is the velocity's
        # anchor, so check the rate through the published YoY of the basis factor.
        from uw_scan.macro.transforms import yoy_from_index

        series = {
            obs.period_end: obs.value
            for obs in _observations(scenario_id)
            if obs.series_id == STATE_BASIS
        }
        computed = yoy_from_index(series, basis.period_end)
        assert computed is not None
        assert round(computed, 2) == Decimal(derived[f"{STATE_BASIS}_yoy_percent"])

    @pytest.mark.parametrize("scenario_id", GOLDEN_INFLATION)
    def test_three_month_changes_match_the_frozen_measurements(
        self, scenario_id: str
    ) -> None:
        derived = SCENARIOS[scenario_id]["derived_from_inputs"]
        state = _state(scenario_id)
        for factor in state.factors:
            key = (
                f"{factor.series_id}_yoy_change_3m_pp"
                if factor.unit.startswith("index")
                else f"{factor.series_id}_change_3m"
            )
            expected = Decimal(derived[key])
            assert factor.change_over_window is not None, factor.series_id
            assert abs(factor.change_over_window - expected) <= ROUNDING_ULP, (
                f"{factor.series_id}: engine {factor.change_over_window} vs frozen "
                f"{expected}"
            )

    @pytest.mark.parametrize("scenario_id", GOLDEN_INFLATION)
    def test_the_state_period_is_the_one_the_publisher_had_released(
        self, scenario_id: str
    ) -> None:
        derived = SCENARIOS[scenario_id]["derived_from_inputs"]
        state = _state(scenario_id)
        for factor in state.factors:
            assert factor.period_end == date.fromisoformat(
                derived[f"{factor.series_id}_latest_period_at_as_of"]
            )

    def test_publisher_transformed_series_are_not_differenced_twice(self) -> None:
        """``MED``/``TRMMEAN`` are already rates; ``CORESTICK`` is already a YoY.

        Their three-month change is a plain difference of levels.  Deriving a YoY from
        them first would report the change of a change, and the suffix that encodes the
        difference -- ``M158`` against ``M159`` -- is absent from both titles.
        """
        state = _state("broad_reacceleration")
        derived = SCENARIOS["broad_reacceleration"]["derived_from_inputs"]
        for series_id in ("MEDCPIM158SFRBCLE", "TRMMEANCPIM158SFRBCLE"):
            factor = state.factor(series_id)
            assert factor is not None
            assert factor.change_over_window is not None
            # A plain difference of two published rates involves no intermediate
            # rounding, so this must agree with the frozen measurement exactly.
            assert round(factor.change_over_window, 2) == Decimal(
                derived[f"{series_id}_change_3m"]
            )


class TestAbsentPeriods:
    """October 2025 CPI does not exist; the shutdown stopped it being published."""

    SCENARIO = "absent_period_from_publication_gap"

    def _series(self) -> dict[date, Decimal]:
        return {obs.period_end: obs.value for obs in _observations(self.SCENARIO)}

    def test_the_missing_period_is_really_missing(self) -> None:
        assert date(2025, 10, 1) not in self._series()
        assert (
            SCENARIOS[self.SCENARIO]["derived_from_inputs"]["target_period_present"]
            is False
        )

    def test_a_pinned_absent_period_abstains(self) -> None:
        scenario = SCENARIOS[self.SCENARIO]
        state = compute_inflation_state(
            _observations(self.SCENARIO),
            as_of=_instant(scenario["as_of"]),
            target_period=date.fromisoformat(scenario["target_period"]),
        )
        assert state.state == "INDETERMINATE"
        assert {r.term for r in state.confidence_reasons} >= set(
            scenario["expect"]["confidence_reasons_include"]
        )

    def test_the_missing_period_is_never_forward_filled(self) -> None:
        scenario = SCENARIOS[self.SCENARIO]
        state = compute_inflation_state(
            _observations(self.SCENARIO),
            as_of=_instant(scenario["as_of"]),
            target_period=date.fromisoformat(scenario["target_period"]),
        )
        assert all(f.period_end != date(2025, 10, 1) for f in state.factors)
        for metric in state.velocity:
            assert metric.value is None
            assert metric.unavailable_reason

    def test_a_three_month_change_is_calendar_anchored_not_positional(self) -> None:
        """The trap the gap sets: three *rows* back from December 2025 is August.

        September is present and December is present, so a calendar-anchored change is
        well defined and equals 326.030 - 324.368.  Counting rows instead silently
        spans four months and reports it as three.
        """
        series = self._series()
        december = date(2025, 12, 1)
        computed = change_over_months(series, december, 3)
        assert computed == Decimal("326.030") - Decimal("324.368")

        positional = sorted(series)[-4]
        assert positional == date(2025, 8, 1), "the row three back is not September"
        assert computed != series[december] - series[positional]

    def test_an_anchor_inside_the_gap_returns_nothing(self) -> None:
        series = self._series()
        # A change ending in January 2026 would need October 2025, which was never
        # published.  There is no substitute for it.
        assert change_over_months(series, shift_months(date(2026, 1, 1), 0), 3) is None


class TestPointInTimeReplay:
    """January 2024 CPI reads 309.685, 309.794 and 309.698 depending on when you ask."""

    SCENARIO = "stale_and_revised_realized_inflation"

    def _at(self, as_of: str, prior_state: Any = None):
        return compute_inflation_state(
            _vintage_observations(self.SCENARIO),
            as_of=_instant(as_of),
            prior_state=prior_state,
        )

    def test_a_replay_returns_the_vintage_that_was_in_force(self) -> None:
        expect = SCENARIOS[self.SCENARIO]["expect"]
        state = self._at(SCENARIOS[self.SCENARIO]["as_of"])
        factor = state.factor("CPIAUCSL")
        assert factor is not None
        assert factor.value == Decimal(expect["state_basis_value"])

    def test_a_replay_never_reads_the_current_value_into_the_past(self) -> None:
        expect = SCENARIOS[self.SCENARIO]["expect"]
        state = self._at(SCENARIOS[self.SCENARIO]["as_of"])
        factor = state.factor("CPIAUCSL")
        assert factor is not None
        assert factor.value != Decimal(expect["must_not_read"])

    def test_a_restatement_penalises_confidence_and_says_which_input(self) -> None:
        expect = SCENARIOS[self.SCENARIO]["expect"]
        before = self._at(SCENARIOS[self.SCENARIO]["as_of"])
        after = self._at("2026-08-18", prior_state=before)

        assert after.factor("CPIAUCSL").value == Decimal(expect["must_not_read"])
        penalty = after.reason("revision_penalty")
        assert penalty is not None and penalty.value > 0
        assert {r.term for r in after.confidence_reasons} >= set(
            expect["confidence_reasons_include"]
        )
        assert "CPIAUCSL" in penalty.detail

    def test_a_newly_published_period_is_not_a_revision(self) -> None:
        """Only a changed value for a period already stated counts."""
        state = self._at(SCENARIOS[self.SCENARIO]["as_of"])
        again = self._at(SCENARIOS[self.SCENARIO]["as_of"], prior_state=state)
        assert again.reason("revision_penalty").value == 0


class TestConfidenceIsKnowledgeNotMagnitude:
    def test_a_larger_signal_does_not_buy_confidence(self) -> None:
        """2022-01 core PCE ran 5.21 against 2023-06's 4.10, and is less trusted.

        A magnitude-driven confidence would rank these the other way round.  What
        separates them is that the 2022 window has two rules firing against it.
        """
        hot = _state("broad_reacceleration")
        cooling = _state("disinflation_with_sticky_services")
        assert hot.state == cooling.state == "WELL_ABOVE_TARGET"
        assert hot.confidence < cooling.confidence

    def test_dropping_an_input_lowers_confidence(self) -> None:
        scenario = SCENARIOS["disinflation_with_sticky_services"]
        full = _state("disinflation_with_sticky_services")
        without_survey = compute_inflation_state(
            _observations(
                "disinflation_with_sticky_services", only=set(REQUIRED) - {"MICH"}
            ),
            as_of=_instant(scenario["as_of"]),
        )
        assert without_survey.confidence < full.confidence
        assert "MICH" in without_survey.reason("completeness").detail

    def test_below_the_completeness_floor_the_state_abstains(self) -> None:
        """The legacy defect: renormalising over surviving weight yields full conviction.

        Three of eight inputs still describe inflation running well above target, and
        the engine must refuse to say so with authority anyway.
        """
        scenario = SCENARIOS["disinflation_with_sticky_services"]
        thin = compute_inflation_state(
            _observations(
                "disinflation_with_sticky_services",
                only={STATE_BASIS, "PCEPI", "CPILFESL"},
            ),
            as_of=_instant(scenario["as_of"]),
        )
        assert thin.reason("completeness").value < Decimal("0.5")
        assert thin.state == "INDETERMINATE"
        assert (
            thin.confidence <= DEFAULT_INFLATION_PARAMETERS.indeterminate_confidence_cap
        )

    def test_a_missing_input_is_never_a_neutral_input(self) -> None:
        """Absence degrades the state; it does not vote for the middle."""
        empty = compute_inflation_state([], as_of=_instant("2023-07-28"))
        assert empty.state == "INDETERMINATE"
        assert empty.direction == "UNKNOWN"
        assert empty.confidence == 0
        assert empty.reason("completeness").value == 0

    def test_a_stale_publisher_is_visible_in_the_freshness_term(self) -> None:
        """Read the same evidence a year later and the state says so."""
        fresh = _state("disinflation_with_sticky_services")
        stale = compute_inflation_state(
            _observations("disinflation_with_sticky_services"),
            as_of=_instant("2024-07-28"),
        )
        assert fresh.reason("freshness").value == 1
        assert stale.reason("freshness").value == 0
        assert stale.confidence == 0


class TestFailClosed:
    def test_a_naive_as_of_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            compute_inflation_state([], as_of=datetime(2023, 7, 28))

    def test_overlapping_vintages_are_a_normalisation_bug_not_a_choice(self) -> None:
        """Two values current at the same instant means picking one silently."""
        overlapping = [
            DomainObservation(
                series_id=obs.series_id,
                causal_role=obs.causal_role,
                period_end=obs.period_end,
                value=obs.value,
                unit=obs.unit,
                publisher_transform=obs.publisher_transform,
                available_at=obs.available_at,
                superseded_at=None,
                source=obs.source,
                source_kind=obs.source_kind,
                cost_class=obs.cost_class,
            )
            for obs in _vintage_observations("stale_and_revised_realized_inflation")
        ]
        with pytest.raises(ValueError, match="overlapping vintages"):
            compute_inflation_state(overlapping, as_of=_instant("2026-08-18"))


class TestInputsHash:
    def test_the_same_evidence_and_parameters_reproduce_the_identity(self) -> None:
        assert (
            _state("disinflation_with_sticky_services").inputs_hash
            == _state("disinflation_with_sticky_services").inputs_hash
        )

    def test_different_evidence_earns_a_different_identity(self) -> None:
        assert (
            _state("disinflation_with_sticky_services").inputs_hash
            != _state("broad_reacceleration").inputs_hash
        )

    def test_a_moved_threshold_earns_a_different_identity(self) -> None:
        """Thresholds are inputs.

        Hiding them in module constants lets a parameter change every state while the
        identity meant to detect the change stays put.
        """
        scenario = SCENARIOS["disinflation_with_sticky_services"]
        moved = compute_inflation_state(
            _observations("disinflation_with_sticky_services"),
            as_of=_instant(scenario["as_of"]),
            parameters=InflationParameters(above_target_upper=Decimal("4.50")),
        )
        assert (
            moved.inputs_hash != _state("disinflation_with_sticky_services").inputs_hash
        )
        assert moved.state == "ABOVE_TARGET", "the moved threshold must actually bite"


class TestSharedConfidenceContract:
    def test_the_penalty_cap_bounds_a_pile_of_contradictions(self) -> None:
        from uw_scan.macro.contracts import Contradiction

        state = _state("disinflation_with_sticky_services")
        _confidence, reasons = compute_confidence(
            state.factors,
            required_series=tuple(REQUIRED),
            contradictions=tuple(
                Contradiction(rule=f"rule_{n}", detail="") for n in range(20)
            ),
            contradiction_penalty_each=DEFAULT_INFLATION_PARAMETERS.contradiction_penalty_each,
            contradiction_penalty_cap=DEFAULT_INFLATION_PARAMETERS.contradiction_penalty_cap,
        )
        penalty = next(r for r in reasons if r.term == "contradiction_penalty")
        assert penalty.value == DEFAULT_INFLATION_PARAMETERS.contradiction_penalty_cap


class TestDormantRulesStateTheirOwnCondition:
    """A rule that cannot fire must say so, and say exactly what would change that.

    ``expectations_diverge_from_realized`` reads factors whose role is
    ``expectations_market``. ``_factors`` only builds factors for series listed in
    ``REQUIRED``, and no entry there carries that role -- so the rule is unreachable
    today. That is deliberate: the design keeps survey expectations and market
    compensation apart, and this rule is where the separation gets enforced once both
    are present.

    The failure this guards against is the one the rates domain actually shipped: a
    dormant rule whose stated wake-up condition was wrong, so the person who satisfied
    it got no rule and no warning.
    """

    def test_no_required_series_carries_the_market_expectations_role(self) -> None:
        roles = {role for role, _cadence in REQUIRED.values()}
        assert "expectations_market" not in roles, (
            "A market-compensation series was added to REQUIRED. "
            "expectations_diverge_from_realized in inflation.py can now fire -- give it "
            "a scenario, and drop the dormancy comment above it."
        )
