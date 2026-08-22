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
from uw_scan.macro.evidence_store import RATES_EVIDENCE
from uw_scan.macro.inflation import compute_inflation_state
from uw_scan.macro.rates import (
    DEFAULT_RATES_PARAMETERS,
    RatesParameters,
    attribute_nominal_change,
    compute_rates_state,
)
from uw_scan.macro.rates_rules import forward_spreads, horizon_years, year_end_rate
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
    """Real Cleveland model output against the real traded yield for one month.

    The roles here are the ones ``RATES_EVIDENCE`` actually assigns, and that is the
    point: the traded 10y is ``curve``, not ``decomposition_component``.  An earlier
    fixture gave ``DGS10`` the role the rule filtered on, which made every case below
    pass against a world production never produces -- the rule could not fire at all
    on real evidence.
    """
    return [
        DomainObservation(
            series_id=series_id,
            causal_role=role,
            period_end=date(2022, 4, 1),
            value=Decimal(value),
            unit="percent",
            publisher_transform="level",
            available_at=_instant("2026-08-18"),
            source=source,
            source_kind="official",
            cost_class="free_official",
        )
        for series_id, role, value, source in (
            ("DGS10", "curve", traded, "fred"),
            (
                "CLEVELAND_MODEL_NOMINAL_10Y",
                "decomposition_component",
                modelled,
                "cleveland_fed",
            ),
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

    def test_the_traded_leg_is_read_under_the_role_production_assigns(self) -> None:
        """The rule must not depend on how the traded yield happens to be tagged.

        ``RATES_EVIDENCE`` calls ``DGS10`` ``curve``.  A rule that only reads
        ``decomposition_component`` therefore never sees it, which is how this check
        spent its whole life unreachable while its tests were green.
        """
        assert {obs.causal_role for obs in _decomposition("2.39", "3.669")} == {
            "curve",
            "decomposition_component",
        }
        assert (
            next(
                contract.causal_role
                for contract in RATES_EVIDENCE
                if contract.series_id == "DGS10"
            )
            == "curve"
        )
        assert self._fired("2.39", "3.669")

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


class TestExpiredHorizonsAreNotCompared:
    """A horizon the calendar has passed is a settled question, not a forecast.

    A release keeps its horizons after the year ends: the December 2026 SEP still
    prints a 2026 year-end dot in January 2027. Both the direction vote and the spread
    comparison reach for the NEAREST horizon, so without a floor they reach for the one
    year whose answer is already known -- and report a lean toward a level that has
    either happened or not. This fires every January in live operation, not only in
    replay.
    """

    def _sep(self):
        return next(path for path in _paths() if path.kind == "committee_projection")

    def test_a_year_that_has_ended_drops_out_of_the_horizons(self) -> None:
        sep = self._sep()
        assert horizon_years(sep)[0] == 2026
        assert horizon_years(sep, not_before=2026)[0] == 2026
        assert horizon_years(sep, not_before=2027)[0] == 2027

    def test_the_direction_vote_reads_the_nearest_future_horizon(self) -> None:
        """Same release, one calendar year later, a different question asked of it."""
        paths = _paths()
        during = compute_rates_state(paths, as_of=_instant("2026-08-18"))
        after = compute_rates_state(paths, as_of=_instant("2027-01-15"))
        # The 2026 dot is what "during" leans on; by 2027-01-15 that year is settled and
        # the vote must move to 2027 rather than re-reading a decided one.
        assert during.direction != "UNKNOWN"
        sep = self._sep()
        assert year_end_rate(sep, 2026) != year_end_rate(sep, 2027)
        assert after.velocity is not None

    def test_a_common_horizon_entirely_in_the_past_is_no_common_horizon(self) -> None:
        by_kind = {path.kind: path for path in _paths() if path.kind != "actual"}
        horizon, _spreads = forward_spreads(by_kind, not_before=2026)
        assert horizon == 2026
        # The market snapshot only prices 2026 meetings, so a year later the two paths
        # share nothing comparable -- which is the honest answer, not a stale spread.
        later, spreads_later = forward_spreads(by_kind, not_before=2027)
        assert later is None
        assert spreads_later == {}


class TestUnreadActionWord:
    """An action word we cannot read must not pass as one we read.

    The statement parser emits a closed vocabulary (Hold / Hike / Cut), so these cases
    stand in for a *different* producer -- the calendar scraper, which lifts its action
    text from the Fed's meeting-calendar HTML -- starting to say something new. The
    rates below are the real frozen scenario values; only the action string is altered,
    because a malformed release is what is being tested.
    """

    def _actual_with_action(self, action: str | None) -> list[PolicyPath]:
        paths = _paths()
        actual = next(path for path in paths if path.kind == "actual")
        altered = actual.model_copy(
            update={
                "points": [
                    point.model_copy(update={"action": action})
                    for point in actual.points
                ]
            }
        )
        return [altered if path.kind == "actual" else path for path in paths]

    def _state_for(self, action: str | None):
        return compute_rates_state(
            self._actual_with_action(action),
            as_of=_instant(SCENARIOS[PATHS_SCENARIO]["as_of"]),
        )

    def test_a_blank_action_is_not_a_stated_one(self) -> None:
        """A whitespace-only action used to crash on an empty ``split()``."""
        blank = self._state_for("   ")
        assert blank.state == self._state_for(None).state
        assert not [note for note in blank.notes if "does not recognise" in note]

    def test_an_unrecognised_action_is_reported_rather_than_discarded(self) -> None:
        state = self._state_for("Recalibrate")
        # One point means no target-range difference to fall back on, so the honest
        # answer is that we do not know -- not a label inferred from a discarded word.
        assert state.state == "INDETERMINATE"
        assert any("'Recalibrate'" in note for note in state.notes)

    def test_a_recognised_action_adds_no_note(self) -> None:
        state = self._state_for("Hold")
        assert state.state == "ON_HOLD"
        assert not [note for note in state.notes if "does not recognise" in note]


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


class TestR2TheMarketLayerNeverGatesThePolicyState:
    """MC3's second ruling, encoded as tests rather than left as a comment.

    ``macro/rates.py:169`` already documents why widening the policy denominator is
    unsafe: it would let the market shadow stand in for an absent dealer path and report
    full coverage. What MC3 changed is presentation, not arithmetic -- once the market
    layer has evidence its sub-states publish their own confidence, and no surface may
    render the policy number beside a sub-state in a way that implies one covers the
    other. The populated cases live in ``test_rates_sub_states.py``, driven by the golden
    fixture; what is asserted here is the structure that must hold with or without them.
    """

    def _state(self, **kwargs: Any):
        return compute_rates_state(
            _paths(), as_of=_instant(SCENARIOS[PATHS_SCENARIO]["as_of"]), **kwargs
        )

    def test_no_market_role_may_enter_the_policy_denominator(self) -> None:
        from uw_scan.macro.rates import _POLICY_ROLES, POLICY_REQUIRED

        market_roles = {"supply", "positioning", "plumbing", "curve"}
        assert not {_POLICY_ROLES[kind] for kind in POLICY_REQUIRED} & market_roles
        assert set(POLICY_REQUIRED) == {
            "actual",
            "committee_projection",
            "dealer_expectations",
        }

    def test_every_role_publishes_a_sub_state_with_its_own_confidence(self) -> None:
        """Including when it has nothing: a role that vanishes reads as undeclared."""
        state = self._state()
        assert [item.role for item in state.sub_states] == [
            "supply",
            "positioning",
            "plumbing",
        ]
        for item in state.sub_states:
            assert item.confidence_reasons
            assert Decimal(0) <= item.confidence <= Decimal(1)
            if item.state == "UNKNOWN":
                assert item.unavailable_reason

    def test_an_absent_market_layer_does_not_lower_the_policy_confidence(self) -> None:
        """The committee's published action is not less certain because CFTC is quiet."""
        state = self._state()
        assert state.confidence > 0
        assert all(item.confidence == 0 for item in state.sub_states)

    def test_each_sub_state_confidence_is_surfaced_next_to_the_policy_one(self) -> None:
        """So a reader cannot mistake one 1.00 for coverage of both."""
        state = self._state()
        for item in state.sub_states:
            term = state.reason(f"sub_state_confidence:{item.role}")
            assert term is not None
            assert term.kind == "informational"
            assert term.value == item.confidence

    def test_market_factors_absent_survives_and_counts_what_is_missing(self) -> None:
        """Kept, not deleted, so a future regression is visible rather than silent."""
        absent = self._state().reason("market_factors_absent")
        assert absent is not None
        assert absent.kind == "informational"
        assert absent.value == Decimal(5)

    def test_market_factors_absent_is_reported_even_at_zero(self) -> None:
        """A term that vanishes when healthy is a term nobody notices coming back."""
        state = compute_rates_state(
            _paths(),
            as_of=_instant(SCENARIOS[PATHS_SCENARIO]["as_of"]),
            observations=_every_market_role(),
        )
        term = state.reason("market_factors_absent")
        assert term is not None
        assert term.value == Decimal(0)
        assert term.kind == "informational"


def _every_market_role() -> list[DomainObservation]:
    """One real observation per market causal role, so none is reported absent.

    Values are real published readings frozen at authoring time: the 10-year note new
    issue of 2026-08-12 at $42bn, the 10-year note future's leveraged-money share for
    report week 2026-08-11, and SOFR/EFFR for 2026-08-19.
    """
    as_of_day = SCENARIOS[PATHS_SCENARIO]["as_of"]
    rows = [
        ("10-Year|Note", "supply", "42000000000", "usd_offering_amount"),
        ("043602|lev_money_net_pct_oi", "positioning", "-39.6365", "pct_open_interest"),
        ("SOFR", "plumbing", "4.35", "percent"),
        ("EFFR", "plumbing", "4.33", "percent"),
        ("DGS10", "curve", "4.24", "percent"),
        ("T10YIE", "decomposition_component", "2.31", "percent"),
    ]
    return [
        DomainObservation(
            series_id=series_id,
            causal_role=role,
            period_end=date.fromisoformat(as_of_day),
            value=Decimal(value),
            unit=unit,
            publisher_transform="level",
            available_at=_instant(as_of_day),
            source="fred",
            source_kind="first_party_publisher",
            cost_class="free_publisher",
        )
        for series_id, role, value, unit in rows
    ]
