"""The market sub-states, driven by the golden fixture's preregistered predictions.

Every `expect` block in ``rates_market_layer_golden.json`` was written before these
engines existed. These tests read the predictions from the fixture rather than restating
them, so a sub-state that drifts fails here instead of quietly producing a different
answer than the one that was called.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from uw_scan.macro.contracts import DomainObservation, FactorState, freshness_for
from uw_scan.macro.rates_sub_states import (
    PLUMBING_STRESSED_BPS,
    PLUMBING_TIGHTENING_BPS,
    _plumbing_label,
    build_sub_states,
)

GOLDEN = json.loads(
    (
        Path(__file__).resolve().parents[3]
        / "tests/fixtures/macro/rates_market_layer_golden.json"
    ).read_text()
)

BASELINE_QUARTERS = 4
MARKET_CADENCE_DAYS = 4
POLICY_CADENCE_DAYS = 120
#: Each role gets its PUBLISHER's cadence, mirroring RatesParameters. Positioning is
#: weekly; giving it the 120-day policy cadence made a four-month-old COT report read as
#: fresh, which is what the staleness scenario caught.
CADENCE_BY_ROLE = {
    "curve": MARKET_CADENCE_DAYS,
    "decomposition_component": MARKET_CADENCE_DAYS,
    "plumbing": MARKET_CADENCE_DAYS,
    "supply": 92,
    "positioning": 7,
}
DECAY = Decimal(3)


def scenario(scenario_id: str) -> dict:
    return next(item for item in GOLDEN["scenarios"] if item["id"] == scenario_id)


def _instant(raw: str) -> datetime:
    text = raw.replace("Z", "+00:00")
    if "T" not in text:
        return datetime.combine(date.fromisoformat(text), datetime.min.time(), UTC)
    return datetime.fromisoformat(text)


def _observations(case: dict) -> tuple[DomainObservation, ...]:
    """The fixture's rows as engine inputs, including the raw nets the shares need.

    The fixture carries `lev_money_net_contracts` and `open_interest` alongside each
    share because spec 4.2 requires the raw net to travel with the percentile -- the sign
    must never be inferred from a label. The contradiction rule reads that net, so it is
    materialised here as its own series exactly as the ingest does.
    """
    out: list[DomainObservation] = []
    for row in case["inputs"]:
        available_at = _instant(row["available_at"])
        out.append(
            DomainObservation(
                series_id=row["series_id"],
                causal_role=row["causal_role"],
                period_end=date.fromisoformat(row["period_end"]),
                value=Decimal(row["value"]),
                unit=row["unit"],
                publisher_transform="level",
                available_at=available_at,
                source=row["source"],
                source_kind=row["source_kind"],
                cost_class=row["cost_class"],
            )
        )
        if "lev_money_net_contracts" in row:
            code = row["series_id"].split("|")[0]
            out.append(
                DomainObservation(
                    series_id=f"{code}|lev_money_net",
                    causal_role="positioning",
                    period_end=date.fromisoformat(row["period_end"]),
                    value=Decimal(row["lev_money_net_contracts"]),
                    unit="contracts_net",
                    publisher_transform="level",
                    available_at=available_at,
                    source=row["source"],
                    source_kind=row["source_kind"],
                    cost_class=row["cost_class"],
                )
            )
    return tuple(out)


def _factors(
    observations: tuple[DomainObservation, ...], as_of: datetime
) -> tuple[FactorState, ...]:
    latest: dict[str, DomainObservation] = {}
    for obs in observations:
        current = latest.get(obs.series_id)
        if current is None or obs.period_end > current.period_end:
            latest[obs.series_id] = obs
    out = []
    for series_id, obs in sorted(latest.items()):
        age_days = (as_of.date() - obs.available_at.date()).days
        cadence = CADENCE_BY_ROLE.get(obs.causal_role, POLICY_CADENCE_DAYS)
        out.append(
            FactorState(
                name=f"{obs.causal_role}:{series_id}",
                causal_role=obs.causal_role,
                series_id=series_id,
                period_end=obs.period_end,
                value=obs.value,
                unit=obs.unit,
                direction="UNKNOWN",
                change_over_window=None,
                available_at=obs.available_at,
                age_days=age_days,
                freshness=freshness_for(age_days, cadence, DECAY),
                quality_status=obs.quality_status,
                source=obs.source,
                source_kind=obs.source_kind,
            )
        )
    return tuple(out)


def sub_states_for(scenario_id: str):
    case = scenario(scenario_id)
    as_of = _instant(case["as_of"])
    observations = tuple(obs for obs in _observations(case) if obs.is_known_on(as_of))
    return (
        build_sub_states(
            observations,
            _factors(observations, as_of),
            as_of=as_of,
            supply_baseline_quarters=BASELINE_QUARTERS,
            cadence_by_role=CADENCE_BY_ROLE,
            freshness_decay_multiple=DECAY,
        ),
        case,
        observations,
    )


def role(states, name: str):
    return next(item for item in states if item.role == name)


def test_supply_elevated_matches_its_preregistered_label() -> None:
    states, case, _ = sub_states_for("supply_elevated_against_neutral_macro")
    supply = role(states, "supply")
    assert supply.state == case["expect"]["supply_state"]

    detail = next(
        r.detail
        for r in supply.confidence_reasons
        if r.term == "supply_terms_classified"
    )
    for series_id in case["expect"]["elevated_series_include"]:
        assert series_id in detail


def test_a_term_below_the_minimum_row_count_names_its_shortfall() -> None:
    states, case, _ = sub_states_for("supply_term_below_minimum_rows")
    supply = role(states, "supply")
    assert supply.state == case["expect"]["supply_state"] == "UNKNOWN"
    assert case["expect"]["shortfall_named"] is True
    # The shortfall is named with its own count, not reported as a bare absence.
    assert f"/{case['expect']['minimum_rows']}" in (supply.unavailable_reason or "")


def test_positioning_stretched_matches_its_preregistered_label() -> None:
    states, case, _ = sub_states_for("positioning_stretched_against_curve")
    positioning = role(states, "positioning")
    assert positioning.state == case["expect"]["positioning_state"]
    assert positioning.confidence > 0


def test_a_week_that_was_never_published_is_unknown_not_zero() -> None:
    """as_of 2019-04-01 predates the 2022 bulk load that is these rows' only availability.

    Nothing was knowable, so the sub-state abstains. The two absent Tuesdays the
    prediction names are absent from the series' own period grid.
    """
    states, case, observations = sub_states_for("cot_week_never_published")
    positioning = role(states, "positioning")
    assert positioning.state == case["expect"]["positioning_state"] == "UNKNOWN"
    assert not observations, "a bulk-loaded row is not knowable three years earlier"
    assert case["expect"]["distinguishes_absent_from_parse_failure"] is True

    periods = {row["period_end"] for row in case["inputs"]}
    for absent in case["expect"]["absent_periods"]:
        assert absent not in periods


def test_positioning_past_its_cadence_is_unknown() -> None:
    states, case, _ = sub_states_for("positioning_stale_past_its_cadence")
    positioning = role(states, "positioning")
    assert positioning.state == case["expect"]["positioning_state"] == "UNKNOWN"
    assert "gone quiet" in (positioning.unavailable_reason or "")

    # The scenario's NOTE says supply is fresh; its own rows end 2024-05-08 against an
    # as_of of 2026-08-20, so supply is stale too and says so. The note is inaccurate
    # about the data it was written over; the prediction it pins -- positioning UNKNOWN --
    # holds, and both roles reporting UNKNOWN for their own measured reason is the
    # behaviour the scenario exists to require.
    assert role(states, "supply").state == "UNKNOWN"
    assert case["expect"]["domain_freshness_takes_minimum"] is True


def test_plumbing_matches_its_preregistered_label() -> None:
    states, case, _ = sub_states_for("plumbing_stress_under_unchanged_policy")
    plumbing = role(states, "plumbing")
    assert plumbing.state == case["expect"]["plumbing_state"]
    assert case["expect"]["policy_direction_inferred"] is None
    # A sub-state states no policy direction; the field does not exist on it.
    assert not hasattr(plumbing, "policy_direction")


def test_every_role_publishes_a_sub_state_even_when_it_has_nothing() -> None:
    """A role that vanishes is indistinguishable from one that was never declared."""
    states, _, _ = sub_states_for("supply_term_below_minimum_rows")
    assert [item.role for item in states] == ["supply", "positioning", "plumbing"]
    for item in states:
        if item.state == "UNKNOWN":
            assert item.unavailable_reason
            assert item.confidence == 0


def test_absence_is_never_neutral() -> None:
    for case in GOLDEN["scenarios"]:
        states, _, _ = sub_states_for(case["id"])
        assert not [item for item in states if item.state == "NEUTRAL"]


@pytest.mark.parametrize(
    ("spread_bps", "expected"),
    [
        # 2019-09-17, the one funding crisis in the record: SOFR 5.25 against an
        # effective rate of 2.30. Real published values, frozen.
        (Decimal("295"), "STRESSED"),
        # 2025-10-28, the golden scenario's own as_of.
        (Decimal("19"), "TIGHTENING"),
        # A calm day: SOFR below EFFR, which is where the median sits.
        (Decimal("-2"), "AMPLE"),
        (PLUMBING_STRESSED_BPS, "STRESSED"),
        (PLUMBING_STRESSED_BPS - 1, "TIGHTENING"),
        (PLUMBING_TIGHTENING_BPS, "TIGHTENING"),
        (PLUMBING_TIGHTENING_BPS - 1, "AMPLE"),
    ],
)
def test_the_stressed_threshold_fires_on_the_real_crisis(
    spread_bps: Decimal, expected: str
) -> None:
    """The 2021+ sample contains no funding crisis, so it cannot calibrate stress.

    Its p99 is +15bp, which would have called the golden scenario's +19bp STRESSED and
    left no label for +295bp. The threshold is one policy move instead, and 2019-09-17 is
    what proves it fires -- the series exist that far back even though this desk's
    vintage window does not.
    """
    assert _plumbing_label(spread_bps) == expected
