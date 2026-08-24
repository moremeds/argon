"""The shared confidence engine, tested where its callers cannot reach.

Every domain engine passes ``compute_confidence`` a factor list it has already shaped,
so a defect that only shows up on an UNSHAPED list is invisible from any of them. That
is exactly the defect this file was written for.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from uw_scan.macro.confidence import compute_confidence
from uw_scan.macro.contracts import FactorState, MacroDomainState

AS_OF = datetime(2026, 8, 21, tzinfo=UTC)


def _factor(
    series_id: str, *, freshness: str = "1.0", value: str = "100"
) -> FactorState:
    return FactorState(
        name=series_id.lower(),
        causal_role="curve",
        series_id=series_id,
        period_end=date(2026, 8, 14),
        value=Decimal(value),
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


def _prior(factors) -> MacroDomainState:
    """A prior state carrying ``factors``, for revision detection only.

    Nothing else on the record is read by ``compute_confidence``; the fields exist
    because the contract is frozen, not because the arithmetic consults them.
    """
    return MacroDomainState(
        domain="usd",
        state="RANGEBOUND",
        direction="FLAT",
        velocity=(),
        confidence=Decimal(1),
        confidence_reasons=(),
        contradictions=(),
        factors=tuple(factors),
        evidence_refs=(),
        engine_version="usd/2",
        inputs_hash="0" * 12,
        as_of=AS_OF,
    )


class TestTheDetailNamesTheSetItMeasured:
    """Completeness counted requirements and reported factors.

    USD and Gold each carry one required anchor beside one optional factor, so both
    shipped ``2/1 load-bearing inputs present`` to production while the value beneath
    was a correct 1/1.  A ratio that reads above its own denominator is not a rounding
    artefact -- it is the numerator and denominator being drawn from different sets,
    and the half of the pair a reader actually sees was the wrong half.
    """

    def test_an_optional_factor_does_not_inflate_the_reported_count(self) -> None:
        _, reasons = _confidence(
            (_factor("DTWEXBGS"), _factor("RTWEXBGS")), ("DTWEXBGS",)
        )
        detail = next(r for r in reasons if r.term == "completeness").detail
        assert detail.startswith("1/1"), detail

    def test_the_reported_count_never_exceeds_its_own_denominator(self) -> None:
        _, reasons = _confidence(
            (_factor("DTWEXBGS"), _factor("RTWEXBGS"), _factor("DTWEXAFEGS")),
            ("DTWEXBGS",),
        )
        detail = next(r for r in reasons if r.term == "completeness").detail
        assert detail.startswith("1/1"), detail

    def test_the_reported_count_agrees_with_the_value_it_explains(self) -> None:
        # The pair must never disagree again, whatever the shape of the factor list.
        _, reasons = _confidence(
            (_factor("DTWEXBGS"), _factor("DTWEXAFEGS")),
            ("DTWEXBGS", "RTWEXBGS"),
        )
        completeness = next(r for r in reasons if r.term == "completeness")
        assert completeness.detail.startswith("1/2"), completeness.detail
        assert completeness.value == Decimal("0.5")

    def test_quality_does_not_report_optional_factors_as_load_bearing(self) -> None:
        # Quality keeps averaging over everything the engine consumed -- an optional
        # input the engine read does bear on how reliable the answer is -- so what has
        # to change is the claim, not the arithmetic.
        _, reasons = _confidence(
            (_factor("DTWEXBGS"), _factor("RTWEXBGS")), ("DTWEXBGS",)
        )
        detail = next(r for r in reasons if r.term == "quality").detail
        assert "2" in detail, detail
        assert "load-bearing" not in detail, detail


class TestRevisionPenaltyMeasuresOneSet:
    """The numerator filtered to required series; the divisor counted every factor.

    A revised anchor beside one optional factor scored 1/2, so the term that exists to
    punish a revision punished it half as hard -- and the optional factor doing the
    halving contributed nothing to the state being revised.  It read 0 across all four
    domains in production only because no series had been revised yet, which is also
    why no caller-level test could have caught it.
    """

    def _revision(self, factors, required):
        return compute_confidence(
            factors,
            required_series=required,
            contradictions=(),
            contradiction_penalty_each=Decimal("0.15"),
            contradiction_penalty_cap=Decimal("0.60"),
            prior_state=_prior((_factor("DTWEXBGS"), _factor("RTWEXBGS"))),
        )

    def test_a_revised_anchor_beside_an_optional_factor_is_penalised_in_full(
        self,
    ) -> None:
        _, reasons = self._revision(
            (_factor("DTWEXBGS", value="101"), _factor("RTWEXBGS")), ("DTWEXBGS",)
        )
        penalty = next(r for r in reasons if r.term == "revision_penalty")
        assert penalty.value == Decimal(1), penalty.detail

    def test_an_optional_factors_own_revision_does_not_penalise(self) -> None:
        # RTWEXBGS is not what the state stands on; a change to it is not a revision
        # of the answer.
        _, reasons = self._revision(
            (_factor("DTWEXBGS"), _factor("RTWEXBGS", value="101")), ("DTWEXBGS",)
        )
        assert next(
            r for r in reasons if r.term == "revision_penalty"
        ).value == Decimal(0)

    def test_half_a_revised_requirement_set_is_half_a_penalty(self) -> None:
        _, reasons = self._revision(
            (_factor("DTWEXBGS", value="101"), _factor("RTWEXBGS")),
            ("DTWEXBGS", "RTWEXBGS"),
        )
        assert next(
            r for r in reasons if r.term == "revision_penalty"
        ).value == Decimal("0.5")
