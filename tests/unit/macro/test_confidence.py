"""The shared confidence engine, tested where its callers cannot reach.

Every domain engine passes ``compute_confidence`` a factor list it has already shaped,
so a defect that only shows up on an UNSHAPED list is invisible from any of them. That
is exactly the defect this file was written for.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from uw_scan.macro.confidence import compute_confidence
from uw_scan.macro.contracts import FactorState

AS_OF = datetime(2026, 8, 21, tzinfo=UTC)


def _factor(series_id: str, *, freshness: str = "1.0") -> FactorState:
    return FactorState(
        name=series_id.lower(),
        causal_role="curve",
        series_id=series_id,
        period_end=date(2026, 8, 14),
        value=Decimal("100"),
        unit="index_jan_2006_100",
        direction="FLAT",
        change_over_window=Decimal("0"),
        available_at=AS_OF,
        age_days=0,
        freshness=Decimal(freshness),
        quality_status="valid",
        source="fred",
        source_kind="first_party_publisher",
    )


def _confidence(factors, required):
    return compute_confidence(
        factors,
        required_series=required,
        contradictions=(),
        contradiction_penalty_each=Decimal("0.15"),
        contradiction_penalty_cap=Decimal("0.60"),
    )


class TestCompletenessCountsRequirementsNotFactors:
    """A present substitute is not a present requirement.

    ``len(factors) / len(required_series)`` reads 1/1 when one required series is
    missing and one unrequired series arrived -- full confidence in a state built
    entirely from a substitute. The two shipped callers pre-filter their factors to the
    required set, so the arithmetic was correct for them by accident and the trap sat
    dormant until a third caller passed a factor it merely REPORTS.

    This is the USD abstention case: ``DTWEXBGS`` absent, ``RTWEXBGS`` present.
    """

    def test_an_unrequired_factor_does_not_satisfy_a_requirement(self) -> None:
        confidence, _ = _confidence((_factor("RTWEXBGS"),), ("DTWEXBGS",))
        assert confidence == Decimal(0)

    def test_completeness_reports_zero_not_one(self) -> None:
        _, reasons = _confidence((_factor("RTWEXBGS"),), ("DTWEXBGS",))
        completeness = next(r for r in reasons if r.term == "completeness")
        assert completeness.value == Decimal(0)

    def test_the_missing_requirement_is_named(self) -> None:
        _, reasons = _confidence((_factor("RTWEXBGS"),), ("DTWEXBGS",))
        assert "DTWEXBGS" in next(r for r in reasons if r.term == "completeness").detail

    def test_a_present_requirement_still_counts(self) -> None:
        confidence, _ = _confidence((_factor("DTWEXBGS"),), ("DTWEXBGS",))
        assert confidence == Decimal(1)

    def test_extra_factors_cannot_push_completeness_past_one(self) -> None:
        # The mirror of the bug: three factors against two requirements read 1.5 under
        # the old arithmetic, and clamp_unit hid it at the very end.
        _, reasons = _confidence(
            (_factor("DTWEXBGS"), _factor("RTWEXBGS"), _factor("DTWEXAFEGS")),
            ("DTWEXBGS", "RTWEXBGS"),
        )
        assert next(r for r in reasons if r.term == "completeness").value == Decimal(1)

    def test_partial_coverage_is_the_matched_fraction(self) -> None:
        _, reasons = _confidence(
            (_factor("DTWEXBGS"), _factor("DTWEXAFEGS")),
            ("DTWEXBGS", "RTWEXBGS"),
        )
        assert next(r for r in reasons if r.term == "completeness").value == Decimal(
            "0.5"
        )


class TestFreshnessTakesTheStalest:
    def test_one_quiet_publisher_makes_the_whole_state_stale(self) -> None:
        # A mean would let three live feeds hide one that stopped.
        _, reasons = _confidence(
            (_factor("DTWEXBGS"), _factor("RTWEXBGS", freshness="0.2")),
            ("DTWEXBGS", "RTWEXBGS"),
        )
        assert next(r for r in reasons if r.term == "freshness").value == Decimal("0.2")
