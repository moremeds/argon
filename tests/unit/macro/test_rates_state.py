"""The rates engine, checked against preregistered golden scenarios.

Every number here was measured before the engine existed. Scenario 3 is the one that
earned its keep: it was written to test "dovish SEP against hawkish market pricing", and
the measured spread turned out to be 7.5bp -- the paths agree. Rather than reach for a
window where they disagreed, the scenario was renamed and inverted to assert the
contradiction stays silent, and the disagreement branch became a labelled threshold test
because no real anchor for it exists (the market path is a live snapshot with no
retrievable history).
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from uw_scan.macro.contracts import DomainObservation
from uw_scan.macro.inflation import compute_inflation_state
from uw_scan.macro.rates import (
    DEFAULT_RATES_PARAMETERS,
    RatesParameters,
    attribute_nominal_change,
    compute_rates_state,
)
from uw_scan.macro.rates_rules import forward_spreads, year_end_rate
from uw_scan.models.macro import PolicyPath, PolicyPathPoint

FIXTURE = (
    Path(__file__).parents[2] / "fixtures" / "macro" / "inflation_rates_golden.json"
)
GOLDEN: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
SCENARIOS: dict[str, Any] = {row["id"]: row for row in GOLDEN["scenarios"]}

PATHS_SCENARIO = "policy_paths_kept_separate"
REAL_LED = "nominal_led_by_real_yields"
SUPPLY = "supply_pressure_with_neutral_macro"


def _instant(day: str) -> datetime:
    return datetime.combine(date.fromisoformat(day), datetime.min.time(), UTC)


def _paths(*, include: set[str] | None = None) -> list[PolicyPath]:
    """Build the three real, independently published paths the scenario froze."""
    rows = {row["path"]: row for row in SCENARIOS[PATHS_SCENARIO]["inputs"]}
    out: list[PolicyPath] = []

    if include is None or "actual" in include:
        actual = rows["actual"]
        out.append(
            PolicyPath(
                kind="actual",
                source=actual["source"],
                source_kind="official",
                source_record_id=f"fomc-statement:{actual['meeting_date']}",
                available_at=_instant(actual["meeting_date"]),
                cost_class="free_official",
                points=[
                    PolicyPathPoint(
                        horizon=actual["meeting_date"],
                        horizon_date=date.fromisoformat(actual["meeting_date"]),
                        rate_percent=Decimal(actual["midpoint"]),
                        target_range_lower_percent=Decimal(
                            actual["target_range_lower"]
                        ),
                        target_range_upper_percent=Decimal(
                            actual["target_range_upper"]
                        ),
                        action=actual["action"],
                        vote_status="stated",
                        vote_split=actual["vote_split"],
                        # Two of 55 statements print a tally with no roster, so an empty
                        # roster means "nobody was named", not "nobody dissented".
                        voter_names_stated=actual["voter_names_stated"],
                    )
                ],
            )
        )

    if include is None or "committee_projection" in include:
        sep = rows["committee_projection"]
        out.append(
            PolicyPath(
                kind="committee_projection",
                source=sep["source"],
                source_kind="official",
                source_record_id=f"fed-sep:{sep['release_date']}",
                available_at=_instant(sep["release_date"]),
                cost_class="free_official",
                points=[
                    PolicyPathPoint(
                        horizon=point["horizon"],
                        rate_percent=Decimal(point["median"]),
                        central_tendency_lower_percent=Decimal(
                            point["central_tendency"][0]
                        ),
                        central_tendency_upper_percent=Decimal(
                            point["central_tendency"][1]
                        ),
                        range_lower_percent=Decimal(point["range"][0]),
                        range_upper_percent=Decimal(point["range"][1]),
                        # An SEP dot is anonymous and belongs to no named participant.
                        vote_status=None,
                    )
                    for point in sep["federal_funds_rate"]
                ],
            )
        )

    if include is None or "market_implied" in include:
        market = rows["market_implied"]
        out.append(
            PolicyPath(
                kind="market_implied",
                source=market["source"],
                source_kind="third_party_shadow",
                source_record_id="fed-watch:2026-08-18",
                available_at=_instant(SCENARIOS[PATHS_SCENARIO]["as_of"]),
                cost_class="free_third_party_shadow",
                delay_status="unknown",
                points=[
                    PolicyPathPoint(
                        horizon=point["meeting_date"],
                        horizon_date=date.fromisoformat(point["meeting_date"]),
                        rate_percent=Decimal(point["implied_rate"]),
                    )
                    for point in market["points"]
                ],
            )
        )
    return out


def _state(**kwargs: Any):
    return compute_rates_state(
        _paths(), as_of=_instant(SCENARIOS[PATHS_SCENARIO]["as_of"]), **kwargs
    )


class TestPolicyPathsAreNeverMerged:
    def test_state_and_direction_match_the_prediction(self) -> None:
        expect = SCENARIOS[PATHS_SCENARIO]["expect"]
        state = _state()
        assert state.state == expect["state"]
        assert state.direction == expect["direction"]

    def test_each_path_is_reported_as_its_own_factor(self) -> None:
        expect = SCENARIOS[PATHS_SCENARIO]["expect"]
        roles = {factor.causal_role for factor in _state().factors}
        assert roles == {
            "policy_actual",
            "policy_committee",
            "policy_market_shadow",
        }
        assert len(expect["paths_reported_separately"]) == len(roles)

    def test_no_output_carries_the_average_of_two_paths(self) -> None:
        """3.8375 is on no dot grid and no contract; it is an averaging artifact."""
        derived = SCENARIOS[PATHS_SCENARIO]["derived_from_inputs"]
        forbidden = Decimal(derived["arithmetic_mean_of_the_two_paths"])
        state = _state()
        values = (
            [factor.value for factor in state.factors]
            + [metric.value for metric in state.velocity]
            + [state.confidence]
        )
        assert forbidden not in [value for value in values if value is not None]

    def test_agreeing_paths_do_not_fire_the_disagreement_rule(self) -> None:
        expect = SCENARIOS[PATHS_SCENARIO]["expect"]
        state = _state()
        fired = {item.rule for item in state.contradictions}
        assert not set(expect["contradictions_exclude"]) & fired

    def test_the_measured_spread_is_the_frozen_one(self) -> None:
        derived = SCENARIOS[PATHS_SCENARIO]["derived_from_inputs"]
        horizon, spreads = forward_spreads({path.kind: path for path in _paths()})
        assert horizon == 2026
        assert list(spreads.values()) == [
            Decimal(derived["committee_vs_market_spread_bp"])
        ]

    def test_the_spread_excludes_the_actual_path(self) -> None:
        """Including spot would measure curve slope and call it disagreement.

        The actual midpoint sits 25bp below the market's end-2026 rate; a spread that
        counted it would fire on a committee and a market that agree about a coming move.
        """
        _horizon, spreads = forward_spreads({path.kind: path for path in _paths()})
        assert all("actual" not in pair for pair in spreads)


class TestAbsentPathsAreNeverFilled:
    def test_a_missing_dealer_path_lowers_confidence_and_is_named(self) -> None:
        state = _state()
        assert state.reason("completeness").value < 1
        assert "NYFED_SME" in state.reason("completeness").detail
        absent = state.reason("policy_paths_absent")
        assert absent is not None and "dealer_expectations" in absent.detail

    def test_the_market_shadow_cannot_stand_in_for_the_dealer_path(self) -> None:
        """Both are 'what someone outside the committee expects'. Only one is evidence."""
        with_shadow = _state()
        without_shadow = compute_rates_state(
            _paths(include={"actual", "committee_projection"}),
            as_of=_instant(SCENARIOS[PATHS_SCENARIO]["as_of"]),
        )
        assert with_shadow.confidence == without_shadow.confidence
        assert with_shadow.reason("market_path_is_a_shadow") is not None

    def test_an_absent_actual_release_abstains_rather_than_inferring(self) -> None:
        state = compute_rates_state(
            _paths(include={"committee_projection", "market_implied"}),
            as_of=_instant(SCENARIOS[PATHS_SCENARIO]["as_of"]),
        )
        assert state.state == "INDETERMINATE"
        assert state.direction == "UNKNOWN"
        assert state.reason("required_period_absent_at_as_of") is not None

    def test_a_path_published_after_as_of_is_not_readable(self) -> None:
        """The SEP landed 2026-06-17; the statement it would be read against did not.

        A replay on the SEP's own release date must see the projection and nothing
        else, because on that date nothing else had been published.
        """
        early = compute_rates_state(_paths(), as_of=_instant("2026-06-17"))
        assert {factor.causal_role for factor in early.factors} == {"policy_committee"}
        assert early.state == "INDETERMINATE"


def _episode(scenario_id: str) -> dict[str, dict[str, Decimal]]:
    """Start/end levels per series for a yield episode, keyed by series then date."""
    out: dict[str, dict[str, Decimal]] = {}
    for row in SCENARIOS[scenario_id]["inputs"]:
        out.setdefault(row["series_id"], {})[row["period_end"]] = Decimal(row["value"])
    return out


def _attribution(scenario_id: str):
    """Attribute the episode's nominal move, reading all three legs at common sessions.

    The breakeven leg is taken as nominal minus real rather than from the frozen
    ``T10YIE`` rows, whose window runs one session longer. That is not a shortcut: FRED
    *defines* ``T10YIE`` as ``DGS10 - DFII10``, and mixing a 2025-01-31 breakeven with a
    2025-01-30 nominal would manufacture a 4bp move out of a calendar mismatch rather
    than measure one.
    """
    scenario = SCENARIOS[scenario_id]
    start = scenario["window"]["first_common_session"]
    end = scenario["window"]["last_common_session"]
    levels = _episode(scenario_id)
    nominal_start, nominal_end = levels["DGS10"][start], levels["DGS10"][end]
    real_start, real_end = levels["DFII10"][start], levels["DFII10"][end]
    return attribute_nominal_change(
        nominal_start=nominal_start,
        nominal_end=nominal_end,
        real_start=real_start,
        real_end=real_end,
        breakeven_start=nominal_start - real_start,
        breakeven_end=nominal_end - real_end,
    )


class TestYieldAttribution:
    @pytest.mark.parametrize("scenario_id", [REAL_LED, SUPPLY])
    def test_the_legs_match_the_frozen_measurements(self, scenario_id: str) -> None:
        derived = SCENARIOS[scenario_id]["derived_from_inputs"]
        result = _attribution(scenario_id)
        assert result.nominal_change_bps == Decimal(derived["nominal_change_bp"])
        assert result.real_change_bps == Decimal(derived["real_change_bp"])
        assert result.breakeven_change_bps == Decimal(derived["breakeven_change_bp"])

    @pytest.mark.parametrize("scenario_id", [REAL_LED, SUPPLY])
    def test_the_attribution_matches_the_prediction(self, scenario_id: str) -> None:
        expect = SCENARIOS[scenario_id]["expect"]
        assert _attribution(scenario_id).attribution == expect["attribution"]

    def test_the_real_leg_carries_more_than_half_the_nominal_move(self) -> None:
        expect = SCENARIOS[REAL_LED]["expect"]
        assert expect["real_share_of_nominal_change"] == "greater_than_half"
        assert _attribution(REAL_LED).real_share_of_nominal > Decimal("0.5")

    def test_the_identity_residual_is_an_identity_and_says_so(self) -> None:
        """FRED derives T10YIE from the other two, so this can never be evidence."""
        derived = SCENARIOS[REAL_LED]["derived_from_inputs"]
        result = _attribution(REAL_LED)
        assert result.identity_residual_bps == Decimal(derived["identity_residual_bp"])
        assert "identity" in derived["identity_note"]

    def test_the_attribution_makes_no_term_premium_claim(self) -> None:
        expect = SCENARIOS[REAL_LED]["expect"]
        assert "describe_curve_slope_as_term_premium" in expect["must_not"]
        note = _attribution(REAL_LED).note.lower()
        assert "term premium" in note and "not an estimate of term premium" in note
        assert expect["term_premium_source_required"] == "cleveland_fed_model"

    def test_flat_compensation_carries_no_inflation_consequence(self) -> None:
        expect = SCENARIOS[SUPPLY]["expect"]
        assert expect["breakeven_change_is_approximately_zero"] is True
        result = _attribution(SUPPLY)
        assert abs(result.breakeven_change_bps) <= (
            DEFAULT_RATES_PARAMETERS.breakeven_flat_bps
        )


class TestSupplyPressure:
    """The 2023 refunding: Treasury raised coupon sizes for the first time in five quarters."""

    def _supply(self) -> list[DomainObservation]:
        block = SCENARIOS[SUPPLY]["supply_history"]
        out: list[DomainObservation] = []
        for tenor, rows in block["auctions"].items():
            for row in rows:
                out.append(
                    DomainObservation(
                        series_id=f"TREASURY_NEW_ISSUE_{tenor.replace('-', '_').upper()}",
                        causal_role="supply",
                        period_end=date.fromisoformat(row["auction_date"]),
                        value=Decimal(row["offering_amount_usd"]),
                        unit=block["unit"],
                        publisher_transform="level",
                        # The refunding announcement states the size about a week before
                        # the auction; that announcement is when it became knowable.
                        available_at=_instant(row["available_at"]),
                        source=block["source"],
                        source_kind=block["source_kind"],
                        cost_class=block["cost_class"],
                    )
                )
        return out

    def _state(self, **kwargs: Any):
        return compute_rates_state(
            [],
            as_of=_instant(SCENARIOS[SUPPLY]["as_of"]),
            observations=self._supply(),
            attribution=_attribution(SUPPLY),
            **kwargs,
        )

    def test_supply_at_a_multi_quarter_high_without_macro_confirmation_fires(
        self,
    ) -> None:
        expect = SCENARIOS[SUPPLY]["expect"]
        fired = {item.rule for item in self._state().contradictions}
        assert set(expect["contradictions_include"]) <= fired

    def test_the_rule_needs_both_halves(self) -> None:
        """Elevated supply alone is not a contradiction; unexplained yields are."""
        confirmed = compute_rates_state(
            [],
            as_of=_instant(SCENARIOS[SUPPLY]["as_of"]),
            observations=self._supply(),
            attribution=attribute_nominal_change(
                nominal_start=Decimal("3.86"),
                nominal_end=Decimal("4.27"),
                real_start=Decimal("1.61"),
                # Same nominal move, but compensation carrying it: macro confirms.
                real_end=Decimal("1.62"),
                breakeven_start=Decimal("2.25"),
                breakeven_end=Decimal("2.65"),
            ),
        )
        assert not confirmed.fired("supply_pressure_without_macro_confirmation")

    def test_supply_is_a_factor_with_its_own_freshness(self) -> None:
        state = self._state()
        supply = [f for f in state.factors if f.causal_role == "supply"]
        assert len(supply) == 2
        assert all(factor.freshness > 0 for factor in supply)
        assert {factor.source_kind for factor in supply} == {"official"}

    def test_supply_does_not_gate_the_policy_state(self) -> None:
        """No FOMC release is present here, and supply cannot substitute for one."""
        assert self._state().state == "INDETERMINATE"

    def test_this_episode_leaves_the_inflation_state_untouched(self) -> None:
        expect = SCENARIOS[SUPPLY]["expect"]
        assert expect["inflation_state_unchanged_by_this_episode"] is True
        baseline = compute_inflation_state(
            [], as_of=_instant(SCENARIOS[SUPPLY]["as_of"])
        )
        with_yields = compute_inflation_state(
            [
                DomainObservation(
                    series_id=series_id,
                    causal_role="expectations_market",
                    period_end=date.fromisoformat(period),
                    value=value,
                    unit="percent",
                    publisher_transform="level",
                    available_at=_instant(period),
                    source="fred",
                    source_kind="first_party_publisher",
                    cost_class="free_publisher",
                )
                for series_id, rows in _episode(SUPPLY).items()
                for period, value in rows.items()
            ],
            as_of=_instant(SCENARIOS[SUPPLY]["as_of"]),
        )
        assert with_yields.state == baseline.state == "INDETERMINATE"
        assert with_yields.direction == baseline.direction


def _decomposition(traded: str, modelled: str) -> list[DomainObservation]:
    """Real Cleveland model output against the real traded yield for one month."""
    return [
        DomainObservation(
            series_id=series_id,
            causal_role="decomposition_component",
            period_end=date(2022, 4, 1),
            value=Decimal(value),
            unit="percent",
            publisher_transform="level",
            available_at=_instant("2026-08-18"),
            source=source,
            source_kind="official",
            cost_class="free_official",
        )
        for series_id, value, source in (
            ("DGS10", traded, "fred"),
            ("CLEVELAND_MODEL_NOMINAL_10Y", modelled, "cleveland_fed"),
        )
    ]


class TestDecompositionReconciliation:
    """Only the model-against-market gap can fail; the other two sums are identities.

    Anchors and calibration: docs/research/2026-08-18-mc2-decomposition-residual/.
    """

    def _fired(self, traded: str, modelled: str) -> bool:
        return compute_rates_state(
            [],
            as_of=_instant("2026-08-18"),
            observations=_decomposition(traded, modelled),
        ).fired("decomposition_components_do_not_reconcile")

    def test_the_2022_repricing_gap_fires(self) -> None:
        # 2022-04: the market traded 2.39 while the monthly model still priced 3.669.
        assert self._fired("2.39", "3.669")

    def test_the_models_ordinary_offset_does_not_fire(self) -> None:
        """A 43bp gap is the resting state, not news.

        The tolerance was calibrated against 332 months precisely so that the model's
        permanent offset from the market stops being reported as a contradiction; at
        25bp this case would have fired, along with two thirds of all months.
        """
        assert not self._fired("4.57", "5.004")  # 2025-01, -43.4bp
        assert not self._fired("3.86", "3.674")  # 2023-07, +18.6bp

    def test_a_25bp_tolerance_would_have_fired_on_the_ordinary_offset(self) -> None:
        """Pins why the default moved, so a future edit back to 25 fails here first."""
        noisy = compute_rates_state(
            [],
            as_of=_instant("2026-08-18"),
            observations=_decomposition("4.57", "5.004"),
            parameters=RatesParameters(decomposition_tolerance_bps=Decimal("25")),
        )
        assert noisy.fired("decomposition_components_do_not_reconcile")
        assert DEFAULT_RATES_PARAMETERS.decomposition_tolerance_bps == Decimal("85")

    def test_a_missing_model_leg_raises_nothing(self) -> None:
        """Absence is not a reconciliation failure."""
        only_traded = [
            obs for obs in _decomposition("4.57", "5.004") if obs.series_id == "DGS10"
        ]
        state = compute_rates_state(
            [], as_of=_instant("2026-08-18"), observations=only_traded
        )
        assert not state.fired("decomposition_components_do_not_reconcile")


class TestPathDisagreementThreshold:
    """No real anchor exists for disagreement, so the edges are pinned deliberately.

    The measured spread between the committee and the market is 7.5bp -- they agree --
    and the market path is a live snapshot with no retrievable history, so there is no
    past window to reach for. Every rate below is a real published SEP median or market
    rate; the *pairings* are constructed to sit either side of the threshold, and are
    labelled as such rather than presented as an observed disagreement.
    """

    def _spread_fires(self, left: str, right: str) -> bool:
        paths = [path for path in _paths(include={"actual"})] + [
            PolicyPath(
                kind="committee_projection",
                source="federal_reserve_sep",
                source_record_id="threshold-probe:committee",
                source_kind="official",
                available_at=_instant("2026-06-17"),
                cost_class="free_official",
                points=[PolicyPathPoint(horizon="2026", rate_percent=Decimal(left))],
            ),
            PolicyPath(
                kind="dealer_expectations",
                source="nyfed_sme",
                source_record_id="threshold-probe:dealer",
                source_kind="official",
                available_at=_instant("2026-06-17"),
                cost_class="free_official",
                points=[PolicyPathPoint(horizon="2026", rate_percent=Decimal(right))],
            ),
        ]
        state = compute_rates_state(paths, as_of=_instant("2026-08-18"))
        return state.fired("policy_paths_disagree")

    def test_exactly_at_the_threshold_stays_silent(self) -> None:
        # 3.875 and 3.625 are both real: the market's end-2026 rate and the current
        # target-range midpoint. Exactly 25bp apart, and the rule needs strictly more.
        assert not self._spread_fires("3.875", "3.625")

    def test_past_the_threshold_fires(self) -> None:
        # 3.875 against the real end-2027 SEP median of 3.60: 27.5bp.
        assert self._spread_fires("3.875", "3.60")

    def test_disagreeing_paths_leave_direction_unknown(self) -> None:
        """Two official forward paths pointing opposite ways is not an average."""
        paths = list(_paths(include={"actual"})) + [
            PolicyPath(
                kind="committee_projection",
                source="federal_reserve_sep",
                source_record_id="threshold-probe:committee",
                source_kind="official",
                available_at=_instant("2026-06-17"),
                cost_class="free_official",
                points=[PolicyPathPoint(horizon="2026", rate_percent=Decimal("4.4"))],
            ),
            PolicyPath(
                kind="dealer_expectations",
                source="nyfed_sme",
                source_record_id="threshold-probe:dealer",
                source_kind="official",
                available_at=_instant("2026-06-17"),
                cost_class="free_official",
                points=[PolicyPathPoint(horizon="2026", rate_percent=Decimal("2.9"))],
            ),
        ]
        state = compute_rates_state(paths, as_of=_instant("2026-08-18"))
        assert state.fired("policy_paths_disagree")
        assert state.direction == "UNKNOWN"
        # Their midpoint, 3.65, is not reported anywhere.
        assert Decimal("3.65") not in [factor.value for factor in state.factors]


class TestInputsHash:
    def test_a_moved_threshold_earns_a_different_identity(self) -> None:
        base = _state()
        moved = compute_rates_state(
            _paths(),
            as_of=_instant(SCENARIOS[PATHS_SCENARIO]["as_of"]),
            parameters=RatesParameters(path_disagreement_bps=Decimal("5")),
        )
        assert base.inputs_hash != moved.inputs_hash
        assert moved.fired("policy_paths_disagree"), "the moved threshold must bite"

    def test_the_paths_are_part_of_the_identity(self) -> None:
        full = _state()
        fewer = compute_rates_state(
            _paths(include={"actual", "committee_projection"}),
            as_of=_instant(SCENARIOS[PATHS_SCENARIO]["as_of"]),
        )
        assert full.inputs_hash != fewer.inputs_hash


class TestFailClosed:
    def test_a_naive_as_of_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            compute_rates_state([], as_of=datetime(2026, 8, 18))

    def test_two_releases_of_one_path_kind_are_rejected(self) -> None:
        doubled = _paths() + _paths(include={"committee_projection"})
        with pytest.raises(ValueError, match="duplicate policy path kind"):
            compute_rates_state(
                doubled, as_of=_instant(SCENARIOS[PATHS_SCENARIO]["as_of"])
            )


class TestHorizonResolution:
    """Two paths label horizons differently, and comparing them raw compares questions.

    The SEP prints a calendar year; a market curve prints meeting dates. Lining them up
    is the step that makes "spread at a common horizon" mean anything at all.
    """

    def test_a_labelled_year_resolves_directly(self) -> None:
        committee = next(
            path for path in _paths() if path.kind == "committee_projection"
        )
        assert year_end_rate(committee, 2026) == Decimal("3.8")
        assert year_end_rate(committee, 2027) == Decimal("3.6")

    def test_meeting_dates_resolve_to_the_last_meeting_of_the_year(self) -> None:
        market = next(path for path in _paths() if path.kind == "market_implied")
        # 2026-09-16 is 3.7157 and 2026-12-09 is 3.875; end-2026 is the December one.
        assert year_end_rate(market, 2026) == Decimal("3.875")

    def test_an_unreachable_horizon_returns_nothing(self) -> None:
        market = next(path for path in _paths() if path.kind == "market_implied")
        assert year_end_rate(market, 2030) is None

    def test_longer_run_is_not_mistaken_for_a_year(self) -> None:
        """The SEP's 'Longer run' median is not a dated projection and must not pair."""
        committee = next(
            path for path in _paths() if path.kind == "committee_projection"
        )
        assert any(point.horizon == "Longer run" for point in committee.points)
        assert year_end_rate(committee, 2029) is None
