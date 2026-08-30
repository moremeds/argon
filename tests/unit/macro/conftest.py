"""One real state per macro domain, built from the frozen golden fixtures.

These exist so an invariant can be asserted over ALL FOUR domains in one place rather
than four times inside four suites that each know only their own engine. The defect that
motivated them was exactly the kind a per-domain suite cannot see: a term that every
domain's contract calls a multiplicand while only some domains put it in the product.

Every value comes from ``tests/fixtures/macro/*_golden.json`` -- real published FOMC,
SEP, FRED and H.10 numbers with their real vintages. Nothing here reaches the network.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from uw_scan.macro.contracts import DomainObservation, MacroDomainState
from uw_scan.macro.gold_state import GoldLensResult, compute_gold_state
from uw_scan.macro.inflation import REQUIRED, compute_inflation_state
from uw_scan.macro.rates import compute_rates_state
from uw_scan.macro.usd import UpstreamState, compute_usd_state
from uw_scan.models.macro import PolicyPath, PolicyPathPoint

_FIXTURES = Path(__file__).parents[2] / "fixtures" / "macro"
_INFLATION_RATES: dict[str, Any] = {
    row["id"]: row
    for row in json.loads(
        (_FIXTURES / "inflation_rates_golden.json").read_text(encoding="utf-8")
    )["scenarios"]
}
_USD_GOLD: dict[str, Any] = {
    row["id"]: row
    for row in json.loads(
        (_FIXTURES / "usd_gold_golden.json").read_text(encoding="utf-8")
    )["scenarios"]
}

_PATHS_SCENARIO = "policy_paths_kept_separate"
_INFLATION_SCENARIO = "disinflation_with_sticky_services"
_USD_SCENARIO = "usd_strength_against_easing_policy"
_GOLD_SCENARIO = "gold_and_real_yields_decoupled_post_2022"


def _day(value: str) -> datetime:
    return datetime.combine(date.fromisoformat(value), datetime.min.time(), UTC)


def _stamp(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def _policy_paths() -> list[PolicyPath]:
    """The three independently published paths the rates scenario froze.

    The market-implied path is included on purpose: it is the one that emits
    ``market_path_is_a_shadow``, the term this suite's invariant was written for.
    """
    rows = {row["path"]: row for row in _INFLATION_RATES[_PATHS_SCENARIO]["inputs"]}
    actual = rows["actual"]
    sep = rows["committee_projection"]
    market = rows["market_implied"]
    return [
        PolicyPath(
            kind="actual",
            source=actual["source"],
            source_kind="official",
            source_record_id=f"fomc-statement:{actual['meeting_date']}",
            available_at=_day(actual["meeting_date"]),
            cost_class="free_official",
            points=[
                PolicyPathPoint(
                    horizon=actual["meeting_date"],
                    horizon_date=date.fromisoformat(actual["meeting_date"]),
                    rate_percent=Decimal(actual["midpoint"]),
                    target_range_lower_percent=Decimal(actual["target_range_lower"]),
                    target_range_upper_percent=Decimal(actual["target_range_upper"]),
                    action=actual["action"],
                    vote_status="stated",
                    vote_split=actual["vote_split"],
                    voter_names_stated=actual["voter_names_stated"],
                )
            ],
        ),
        PolicyPath(
            kind="committee_projection",
            source=sep["source"],
            source_kind="official",
            source_record_id=f"fed-sep:{sep['release_date']}",
            available_at=_day(sep["release_date"]),
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
                    vote_status=None,
                )
                for point in sep["federal_funds_rate"]
            ],
        ),
        PolicyPath(
            kind="market_implied",
            source=market["source"],
            source_kind="third_party_shadow",
            source_record_id="fed-watch:2026-08-18",
            available_at=_day(_INFLATION_RATES[_PATHS_SCENARIO]["as_of"]),
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
        ),
    ]


def _policy_paths_keeping(kinds: set[str]) -> list[PolicyPath]:
    return [path for path in _policy_paths() if path.kind in kinds]


def _inflation_observations() -> list[DomainObservation]:
    scenario = _INFLATION_RATES[_INFLATION_SCENARIO]
    return [
        DomainObservation(
            series_id=series_id,
            causal_role=REQUIRED[series_id][0],
            period_end=date.fromisoformat(row["period_end"]),
            value=Decimal(row["value"]),
            unit=block["unit"],
            publisher_transform=block["publisher_transform"],
            available_at=_day(row["available_at"]),
            source="fred",
            source_kind="first_party_publisher",
            cost_class="free_publisher",
        )
        for series_id, block in scenario["observation_history"].items()
        for row in block["observations"]
    ]


def _usd_gold_observation(row: dict[str, Any], obs_id: int) -> DomainObservation:
    return DomainObservation(
        series_id=row["series_id"],
        causal_role=row["causal_role"],
        period_end=date.fromisoformat(row["period_end"]),
        value=Decimal(row["value"]),
        unit=row["unit"],
        publisher_transform="level",
        available_at=_stamp(row["available_at"]),
        superseded_at=(
            _stamp(row["superseded_at"]) if row.get("superseded_at") else None
        ),
        source=row["source"],
        # The fixture predates the source-kind vocabulary these engines read; "vendor"
        # is its word for what the contracts call an entitled provider.
        source_kind=(
            "entitled_provider"
            if row["source_kind"] == "vendor"
            else row["source_kind"]
        ),
        cost_class=row["cost_class"],
        obs_id=obs_id,
    )


def _scenario_as_of(scenario: dict[str, Any]) -> datetime:
    raw = scenario["as_of"]
    return _stamp(raw[0] if isinstance(raw, list) else raw)


@pytest.fixture(scope="session")
def rates_domain_state() -> MacroDomainState:
    return compute_rates_state(
        _policy_paths(), as_of=_day(_INFLATION_RATES[_PATHS_SCENARIO]["as_of"])
    )


@pytest.fixture(scope="session")
def rates_state_missing_two_policy_paths() -> MacroDomainState:
    """A rates state whose ``policy_paths_absent`` count is 2 rather than 1.

    The scenario above is missing exactly one required path, so the count it carries is
    ``Decimal(1)`` -- which is a no-op as a multiplicand AND sits inside ``[0, 1]``. Both
    guards in ``test_confidence_term_kinds`` therefore pass on it whether that term's
    ``kind`` is right or wrong: reverting the fix on ``policy_paths_absent`` was measured
    to leave the whole suite green. One is the single count that hides this defect.

    Dropping ``committee_projection`` as well makes it 2, where a multiplicand doubles a
    confidence it never touched and leaves the fraction range -- so both guards bite.
    """
    return compute_rates_state(
        _policy_paths_keeping({"actual", "market_implied"}),
        as_of=_day(_INFLATION_RATES[_PATHS_SCENARIO]["as_of"]),
    )


@pytest.fixture(scope="session")
def inflation_domain_state() -> MacroDomainState:
    return compute_inflation_state(
        _inflation_observations(),
        as_of=_day(_INFLATION_RATES[_INFLATION_SCENARIO]["as_of"]),
    )


@pytest.fixture(scope="session")
def usd_domain_state() -> MacroDomainState:
    scenario = _USD_GOLD[_USD_SCENARIO]
    owned = tuple(
        _usd_gold_observation(row, obs_id)
        for obs_id, row in enumerate(scenario["inputs"], start=1)
        if row["owned_by"] == "usd"
    )
    return compute_usd_state(
        owned,
        as_of=_scenario_as_of(scenario),
        upstream=(
            UpstreamState(
                domain="policy_rates",
                state="EASING",
                direction="FALLING",
                inputs_hash="0" * 64,
                as_of=datetime(2024, 12, 31, tzinfo=UTC),
                confidence=Decimal("1.0"),
            ),
        ),
    )


@pytest.fixture(scope="session")
def gold_domain_state() -> MacroDomainState:
    scenario = _USD_GOLD[_GOLD_SCENARIO]
    observations = tuple(
        _usd_gold_observation(row, obs_id)
        for obs_id, row in enumerate(scenario["inputs"], start=1)
    )
    as_of = _scenario_as_of(scenario)
    return compute_gold_state(
        observations,
        as_of=as_of,
        lens=GoldLensResult(obs_date=as_of.date(), gauge_state="operative"),
    )
