"""The market layer's parsers, checked against the preregistered golden fixture.

The `expect` blocks in ``tests/fixtures/macro/rates_market_layer_golden.json`` were frozen
before this module existed.  Where a scenario pins a value these tests read it from the
fixture rather than restating it, so a parser that drifts fails here instead of quietly
producing a different number than the one that was predicted.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from uw_scan.macro.rates_market import (
    MARKET_SERIES_CONTRACT,
    load_event_instants,
    parse_positioning_observations,
    parse_supply_observations,
    positioning_artifact,
    supply_artifact,
)
from uw_scan.normalize import NormalizationError
from uw_scan.sources.cftc_tff import parse_treasury_rows

GOLDEN = json.loads(
    (
        Path(__file__).resolve().parents[3]
        / "tests/fixtures/macro/rates_market_layer_golden.json"
    ).read_text()
)

RETRIEVED_AT = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


def scenario(scenario_id: str) -> dict:
    return next(item for item in GOLDEN["scenarios"] if item["id"] == scenario_id)


#: The real publisher payloads, captured 2026-08-21 and shared with the integration
#: test so both layers parse the same bytes.  See the file's own provenance block.
PAYLOADS = json.loads(
    (
        Path(__file__).resolve().parents[3]
        / "tests/fixtures/macro/rates_market_publisher_payloads.json"
    ).read_text()
)


def payload(key: str) -> bytes:
    return json.dumps(PAYLOADS[key]).encode()


AUCTIONS = payload("auctions")
STRETCHED = payload("positioning_stretched")
HOLIDAY = payload("positioning_holiday")
BULK_LOADED = payload("positioning_bulk_loaded")


def supply(payload: bytes = AUCTIONS) -> list:
    return parse_supply_observations(
        payload, request_type="Note", retrieved_at=RETRIEVED_AT
    )


def test_supply_series_key_separates_a_tips_from_a_nominal_note() -> None:
    """The taxonomy collision spec 2.1 measured, as a test.

    Both 10-year rows carry ``securityTerm='10-Year'`` and ``securityType='Note'``.  If the
    series key were the term alone, the $21bn TIPS would enter the $42bn nominal series and
    the multi-quarter-high rule would read the alternation as a supply cut every quarter.
    """
    observations = supply()
    assert [(item.series_id, item.value_numeric) for item in observations] == [
        ("30-Year|Bond", Decimal("25000000000")),
        ("10-Year|Note", Decimal("42000000000")),
    ]


def test_supply_excludes_reopenings_and_unregistered_terms() -> None:
    """A reopening is a marginal add, and a bill is not duration supply."""
    assert not [item for item in supply() if item.period_end == date(2026, 8, 17)]


def test_supply_availability_is_the_announcement_not_the_auction() -> None:
    """Treasury states the size about a week before it sells it.

    Dating availability to the auction would claim we learned the size seven days later
    than we did, and would misalign supply against a curve that had already moved on the
    announcement.
    """
    ten_year = next(item for item in supply() if item.series_id == "10-Year|Note")
    assert ten_year.period_end == date(2026, 8, 12)
    assert ten_year.available_at == datetime(2026, 8, 5, 4, tzinfo=UTC)  # 00:00 ET
    assert ten_year.availability_basis == "publisher_announcement"
    # The feed gives a date and no time of day; an 11:00 ET stamp would be invented.
    assert ten_year.published_at is None
    assert ten_year.available_at < RETRIEVED_AT


def test_supply_matches_the_frozen_golden_unit_and_role() -> None:
    frozen = scenario("supply_elevated_against_neutral_macro")["inputs"][0]
    ten_year = next(item for item in supply() if item.series_id == frozen["series_id"])
    assert (ten_year.unit, ten_year.causal_role) == (
        frozen["unit"],
        frozen["causal_role"],
    )


def test_supply_empty_payload_is_a_failure_not_a_quiet_zero() -> None:
    """Treasury does not stop auctioning, so an empty body is transport or schema."""
    with pytest.raises(NormalizationError, match="empty body"):
        supply(b"")
    with pytest.raises(NormalizationError, match="no readable auction"):
        supply(b"[]")


def test_positioning_share_reproduces_the_frozen_golden_value() -> None:
    """Four decimal places, matching the value preregistered before this parser existed.

    The legacy row quantizes this share to 0.1 for display.  A percentile taken over a
    rounded series collapses distinct weeks onto one value near the tails -- which is
    exactly where a "stretched" label is decided.
    """
    frozen = scenario("positioning_stretched_against_curve")["inputs"][0]
    observations = parse_positioning_observations(STRETCHED)
    share = next(
        item
        for item in observations
        if item.series_id == frozen["series_id"]
        and item.period_end == date.fromisoformat(frozen["period_end"])
    )
    assert share.value_numeric == Decimal(frozen["value"])
    assert share.unit == frozen["unit"]

    net = next(
        item
        for item in observations
        if item.series_id == "043602|lev_money_net"
        and item.period_end == share.period_end
    )
    # The raw net travels with the share, so the sign is never inferred from a label.
    assert net.value_numeric == Decimal(frozen["lev_money_net_contracts"])


def test_positioning_availability_is_the_publisher_instant() -> None:
    frozen = scenario("positioning_stretched_against_curve")["inputs"][0]
    share = next(
        item
        for item in parse_positioning_observations(STRETCHED)
        if item.period_end == date.fromisoformat(frozen["period_end"])
    )
    expected = datetime.fromisoformat(frozen["available_at"].replace("Z", "+00:00"))
    assert share.available_at == expected
    assert share.published_at == expected
    assert share.availability_basis == frozen["availability_basis"]


def test_holiday_shifted_release_is_not_knowable_early() -> None:
    """Golden scenario 5, which pins the retired ``obs_date + 3 days`` rule as lookahead.

    CFTC loaded report 2026-06-16 on the Monday after Juneteenth.  The rule said the
    Friday.  An ``as_of`` inside that gap must see nothing: the alternative is a replay
    reading a position that had not been published.
    """
    case = scenario("holiday_shifted_release_is_not_knowable_early")
    as_of = datetime.fromisoformat(case["as_of"].replace("Z", "+00:00"))
    observations = parse_positioning_observations(HOLIDAY)

    assert observations, "the payload carries one real report week"
    assert not [item for item in observations if item.available_at <= as_of]
    assert case["expect"]["row_visible_at_as_of"] is False

    derived = datetime.combine(
        date.fromisoformat(case["inputs"][0]["period_end"]) + timedelta(days=3),
        datetime.min.time(),
        UTC,
    )
    assert derived <= as_of
    assert case["expect"]["derived_rule_would_have_shown_it"] is True


def test_bulk_loaded_rows_claim_no_publication_instant() -> None:
    """R1, applied exactly where measurement said it still belongs.

    One ``:created_at`` covering more than one report date is a load event, not a release.
    Recording it as a publication would assert that every week it covers became knowable on
    the same afternoon.
    """
    rows = parse_treasury_rows(BULK_LOADED)
    load_instant = datetime(2022, 9, 13, 14, 16, 9, 4000, tzinfo=UTC)
    assert load_event_instants(rows) == frozenset({load_instant})

    for item in parse_positioning_observations(BULK_LOADED):
        assert item.published_at is None
        assert item.available_at == load_instant
        assert item.availability_basis == "bulk_load_conservative"


def test_a_single_report_week_is_a_release_not_a_load() -> None:
    """The detector keys on span, so one week under one instant stays a publication."""
    assert load_event_instants(parse_treasury_rows(HOLIDAY)) == frozenset()


def test_every_parsed_series_is_a_registered_contract() -> None:
    """An unregistered series would reach an engine with no declared unit or role."""
    parsed = supply() + parse_positioning_observations(STRETCHED)
    assert parsed
    for item in parsed:
        assert item.series_id in MARKET_SERIES_CONTRACT


def test_artifacts_are_vintage_bearing_and_carry_no_release_instant() -> None:
    """Both payloads REPORT a publication history rather than being a publication.

    Without ``vintage_bearing``, the read path bounds every row on when we fetched the
    bytes, and a replay before that date returns nothing at all -- which reads as missing
    data rather than as a broken query.
    """
    for artifact in (
        supply_artifact(
            AUCTIONS, request_type="Note", source_url="x", retrieved_at=RETRIEVED_AT
        ),
        positioning_artifact(STRETCHED, source_url="y", retrieved_at=RETRIEVED_AT),
    ):
        assert artifact.vintage_bearing is True
        assert artifact.published_at is None
        assert artifact.available_at == RETRIEVED_AT
        assert artifact.source_kind == "official"
        assert artifact.cost_class == "free_official"


def test_the_fixture_carries_every_scenario_the_spec_lists() -> None:
    """Spec 7 names seven; a spec that claims a scenario the fixture lacks is a lie.

    The plumbing scenario landed last because it needed FRED series that were not
    registered until Task A4, and it is preregistered like the rest -- written before any
    plumbing sub-state exists to be measured against.
    """
    assert {item["id"] for item in GOLDEN["scenarios"]} == {
        "supply_elevated_against_neutral_macro",
        "positioning_stretched_against_curve",
        "plumbing_stress_under_unchanged_policy",
        "cot_week_never_published",
        "holiday_shifted_release_is_not_knowable_early",
        "positioning_stale_past_its_cadence",
        "supply_term_below_minimum_rows",
    }


def test_the_plumbing_scenario_holds_the_policy_target_still() -> None:
    """Its whole point is plumbing moving while policy does not.

    If the effective rate moved with the target inside the window, the scenario would be
    measuring a policy change and calling it a funding condition. It ends the day before
    the 2025-10-29 cut for exactly that reason.
    """
    case = scenario("plumbing_stress_under_unchanged_policy")
    effr = [
        Decimal(row["value"]) for row in case["inputs"] if row["series_id"] == "EFFR"
    ]
    assert max(effr) - min(effr) <= Decimal("0.05")
    assert case["expect"]["policy_direction_inferred"] is None

    # SOFR above EFFR on every day of the window is the funding signal itself.
    by_day = {
        (row["series_id"], row["period_end"]): Decimal(row["value"])
        for row in case["inputs"]
    }
    days = sorted({row["period_end"] for row in case["inputs"]})
    assert all(by_day[("SOFR", d)] > by_day[("EFFR", d)] for d in days)
