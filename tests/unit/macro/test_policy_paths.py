from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from uw_scan.macro.policy import assemble_policy_paths
from uw_scan.models import PolicyPath, PolicyPathPoint


AS_OF = datetime(2026, 6, 18, tzinfo=UTC)


def _path(
    kind: str,
    *,
    rate: Decimal,
    source: str,
    cost_class: str = "free_official",
    delay_minutes: int | None = None,
) -> PolicyPath:
    return PolicyPath(
        kind=kind,
        source=source,
        source_record_id=f"{source}:2026-06",
        published_at=datetime(2026, 6, 17, 18, tzinfo=UTC),
        available_at=datetime(2026, 6, 17, 18, tzinfo=UTC),
        cost_class=cost_class,
        delay_minutes=delay_minutes,
        points=[
            PolicyPathPoint(
                horizon="2026",
                horizon_date=date(2026, 12, 31),
                rate_percent=rate,
            )
        ],
    )


def test_policy_assembler_preserves_disagreement_without_averaging() -> None:
    committee = _path(
        "committee_projection",
        rate=Decimal("3.8"),
        source="federal_reserve_sep",
    )
    dealer = _path(
        "dealer_expectations",
        rate=Decimal("3.13"),
        source="new_york_fed_sme",
    )

    comparison = assemble_policy_paths([committee, dealer], as_of=AS_OF)

    assert comparison.committee_projection.path is committee
    assert comparison.dealer_expectations.path is dealer
    assert comparison.committee_projection.path.points[0].rate_percent == Decimal("3.8")
    assert comparison.dealer_expectations.path.points[0].rate_percent == Decimal("3.13")
    assert comparison.actual.path is None
    assert comparison.actual.missing_reason == "no PIT-eligible actual policy release"
    assert comparison.market_implied.path is None
    assert any("67 bps" in item for item in comparison.contradictions)


def test_policy_assembler_rejects_duplicate_kind() -> None:
    first = _path("committee_projection", rate=Decimal("3.8"), source="fed-sep-a")
    second = _path("committee_projection", rate=Decimal("3.6"), source="fed-sep-b")

    with pytest.raises(ValueError, match="duplicate policy path kind"):
        assemble_policy_paths([first, second], as_of=AS_OF)


def test_removing_one_path_does_not_mutate_another() -> None:
    committee = _path(
        "committee_projection",
        rate=Decimal("3.8"),
        source="federal_reserve_sep",
    )
    dealer = _path(
        "dealer_expectations",
        rate=Decimal("3.13"),
        source="new_york_fed_sme",
    )
    full = assemble_policy_paths([committee, dealer], as_of=AS_OF)
    without_dealer = assemble_policy_paths([committee], as_of=AS_OF)

    assert full.committee_projection.path.model_dump() == (
        without_dealer.committee_projection.path.model_dump()
    )
    assert without_dealer.dealer_expectations.path is None


def test_market_shadow_requires_explicit_cost_and_delay_labels() -> None:
    with pytest.raises(ValueError, match="free_third_party_shadow"):
        _path(
            "market_implied",
            rate=Decimal("3.5"),
            source="Frenzy Capital Fed Watch",
        )

    with pytest.raises(ValueError, match="delay_minutes"):
        _path(
            "market_implied",
            rate=Decimal("3.5"),
            source="Frenzy Capital Fed Watch",
            cost_class="free_third_party_shadow",
        )

    shadow = _path(
        "market_implied",
        rate=Decimal("3.5"),
        source="Frenzy Capital Fed Watch",
        cost_class="free_third_party_shadow",
        delay_minutes=15,
    )
    comparison = assemble_policy_paths([shadow], as_of=AS_OF)
    assert comparison.market_implied.path is shadow
    assert comparison.market_implied.path.delay_minutes == 15


def test_assembler_rejects_path_not_available_as_of() -> None:
    future = _path(
        "committee_projection",
        rate=Decimal("3.8"),
        source="federal_reserve_sep",
    ).model_copy(update={"available_at": datetime(2026, 6, 19, tzinfo=UTC)})

    with pytest.raises(ValueError, match="available after comparison as_of"):
        assemble_policy_paths([future], as_of=AS_OF)
