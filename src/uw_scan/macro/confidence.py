"""The confidence a domain state is entitled to, given what it actually knows.

Shared by every domain engine on purpose.  Confidence is a function of coverage,
freshness, publisher quality, revisions and contradictions -- never of how large the
signal is.  A magnitude-driven confidence rises exactly when the data turns extreme,
which is when it deserves the least trust.

The defect this replaces: a composite that renormalises over surviving weight reports
full conviction from one populated group out of six, and a missing input that maps to
"neutral" renders absence as a considered view.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from .contracts import (
    ConfidenceTerm,
    Contradiction,
    FactorState,
    MacroDomainState,
    clamp_unit,
)

#: Terms every state reports, in the order they multiply.
PRODUCT_TERMS = (
    "completeness",
    "freshness",
    "quality",
    "revision_penalty",
    "contradiction_penalty",
)


def compute_confidence(
    factors: Sequence[FactorState],
    *,
    required_series: Sequence[str],
    contradictions: Sequence[Contradiction],
    contradiction_penalty_each: Decimal,
    contradiction_penalty_cap: Decimal,
    prior_state: MacroDomainState | None = None,
    absent_reason: str | None = None,
) -> tuple[Decimal, tuple[ConfidenceTerm, ...]]:
    """Return the confidence and the per-term breakdown that produced it.

    ``absent_reason`` is set by the caller when a period the state was asked to
    describe was never published; it is recorded as its own reason so an operator can
    tell "we do not know" apart from "we know it is unremarkable".
    """
    present = len(factors)
    required = len(required_series)
    completeness = Decimal(present) / Decimal(required) if required else Decimal(0)
    missing = sorted(set(required_series) - {factor.series_id for factor in factors})

    # Weighted minimum, not a mean: one input that has gone quiet past its own cadence
    # makes the whole state stale, and a mean lets several fresh inputs hide it.
    stalest = min(factors, key=lambda f: f.freshness) if factors else None
    freshness = stalest.freshness if stalest else Decimal(0)
    quality = (
        sum((_quality_weight(f) for f in factors), Decimal(0)) / Decimal(present)
        if present
        else Decimal(0)
    )

    revised = revised_series(factors, prior_state, required_series=required_series)
    revision_penalty = (
        Decimal(len(revised)) / Decimal(present) if present and revised else Decimal(0)
    )
    contradiction_penalty = min(
        contradiction_penalty_each * len(contradictions), contradiction_penalty_cap
    )

    confidence = clamp_unit(
        completeness
        * freshness
        * quality
        * (Decimal(1) - revision_penalty)
        * (Decimal(1) - contradiction_penalty)
    )

    reasons = [
        ConfidenceTerm(
            "completeness",
            completeness,
            f"{present}/{required} load-bearing inputs present"
            + (f"; missing {', '.join(missing)}" if missing else ""),
        ),
        ConfidenceTerm(
            "freshness",
            freshness,
            f"stalest input {stalest.series_id} at {stalest.age_days}d"
            if stalest
            else "no load-bearing input present",
        ),
        ConfidenceTerm(
            "quality",
            quality,
            "mean publisher quality weight over present load-bearing inputs",
        ),
        ConfidenceTerm(
            "revision_penalty",
            revision_penalty,
            f"revised since the prior state: {', '.join(revised)}"
            if revised
            else "no load-bearing input revised since the prior state",
        ),
        ConfidenceTerm(
            "contradiction_penalty",
            contradiction_penalty,
            f"{len(contradictions)} rule(s) fired: "
            + (", ".join(item.rule for item in contradictions) or "none"),
        ),
    ]
    if revised:
        reasons.append(
            ConfidenceTerm(
                "load_bearing_input_revised_since_prior_state",
                Decimal(len(revised)),
                f"{', '.join(revised)} changed value for a period already stated",
            )
        )
    if absent_reason is not None:
        reasons.append(
            ConfidenceTerm("required_period_absent_at_as_of", Decimal(1), absent_reason)
        )
    return confidence, tuple(reasons)


def revised_series(
    factors: Sequence[FactorState],
    prior_state: MacroDomainState | None,
    *,
    required_series: Sequence[str],
) -> list[str]:
    """Series whose already-stated period now carries a different value.

    A new period arriving is not a revision -- that is the publisher doing its job.
    Only a changed value for a period the prior state already stood on is one.
    """
    if prior_state is None:
        return []
    required = set(required_series)
    prior = {
        factor.series_id: factor
        for factor in prior_state.factors
        if factor.series_id in required
    }
    return sorted(
        factor.series_id
        for factor in factors
        if factor.series_id in prior
        and prior[factor.series_id].period_end == factor.period_end
        and prior[factor.series_id].value != factor.value
    )


def _quality_weight(factor: FactorState) -> Decimal:
    return Decimal("1.0") if factor.quality_status == "valid" else Decimal("0.5")
