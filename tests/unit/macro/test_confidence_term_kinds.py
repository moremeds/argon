"""``kind`` must describe what the arithmetic actually did with a term.

The defect: ``market_path_is_a_shadow`` is appended AFTER ``compute_confidence`` has
already returned its number (``macro/rates.py:217``), so it is in the product of
precisely nothing -- and it carried the dataclass default ``kind="multiplicand"``
anyway. Its own ``detail`` says it "contributes no confidence"; its ``kind`` said it
multiplied the state by ``value=0``. Consumers believe the machine-readable half:
``web/components/rates/sections/StateSection.tsx`` filters
``kind === "multiplicand" && value < 1`` into a "Reduced by" strip, so ``/rates`` told
the operator confidence was cut by "x0.00" beside a confidence of 0.850.

Nothing in the engines could catch that. ``confidence`` and ``confidence_reasons`` are
computed independently and never checked against each other, which is what let a term's
label drift away from its role while every domain test kept passing. So the guard here
is the check nobody was doing: fold the reasons back up using ONLY ``kind``, and require
the result to be the confidence the domain reported.

Two shapes of the bug, two tests:
  * a term OUTSIDE the product mislabelled as inside it -- caught by reconciliation;
  * a COUNT mislabelled as a multiplier -- caught by the range rule, because a
    multiplicand and a penalty are both fractions and a count is not.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from uw_scan.macro.contracts import ConfidenceTerm, MacroDomainState, clamp_unit

DOMAIN_FIXTURES = (
    "inflation_domain_state",
    "rates_domain_state",
    "usd_domain_state",
    "gold_domain_state",
)

#: The four above are one real state per engine. The fifth is a second rates scenario,
#: and it exists because the first four cannot fail on the count half of this defect: in
#: every one of them ``policy_paths_absent`` is exactly 1, which multiplies to a no-op
#: and is a legal fraction. Reverting ``kind="informational"`` on that term was measured
#: to leave all four green. See the fixture's own docstring.
STATE_FIXTURES = (*DOMAIN_FIXTURES, "rates_state_missing_two_policy_paths")


def refold(reasons: tuple[ConfidenceTerm, ...]) -> Decimal:
    """Rebuild a confidence from its terms using ``kind`` and nothing else.

    Deliberately blind to term NAMES. Matching on strings is how a consumer ends up
    re-deriving the producer's arithmetic, which is the coupling ``kind`` exists to
    remove -- and a test that special-cased ``market_path_is_a_shadow`` by name would
    have gone on passing through exactly the defect it was meant to detect.
    """
    out = Decimal(1)
    for reason in reasons:
        if reason.kind == "multiplicand":
            out *= reason.value
        elif reason.kind == "penalty":
            out *= Decimal(1) - reason.value
    return clamp_unit(out)


@pytest.mark.parametrize("fixture_name", STATE_FIXTURES)
def test_the_reported_confidence_is_what_its_terms_fold_up_to(
    fixture_name: str, request: pytest.FixtureRequest
) -> None:
    """The whole invariant, on a real state from each of the four engines."""
    state: MacroDomainState = request.getfixturevalue(fixture_name)
    assert refold(state.confidence_reasons) == state.confidence, (
        f"{state.domain} reports {state.confidence} but its terms fold to "
        f"{refold(state.confidence_reasons)}: "
        + "; ".join(
            f"{r.term}={r.value}({r.kind})"
            for r in state.confidence_reasons
            if r.kind != "informational"
        )
    )


@pytest.mark.parametrize("fixture_name", STATE_FIXTURES)
def test_a_term_in_the_product_is_a_fraction_and_never_a_count(
    fixture_name: str, request: pytest.FixtureRequest
) -> None:
    """Counts are the other half of this bug class.

    ``policy_paths_absent`` and ``market_factors_absent`` both carry "how many are
    missing". Left as multiplicands they claim a state was multiplied by 2, and the
    absence they name has ALREADY been priced once, inside ``completeness``. A value
    outside [0, 1] cannot be either kind of multiplier, so it must be informational.
    """
    state: MacroDomainState = request.getfixturevalue(fixture_name)
    for reason in state.confidence_reasons:
        if reason.kind == "informational":
            continue
        assert Decimal(0) <= reason.value <= Decimal(1), (
            f"{state.domain}.{reason.term} is a {reason.kind} carrying "
            f"{reason.value}; a multiplier is a fraction, so this is a count and "
            "belongs to kind='informational'"
        )


def test_the_market_shadow_is_reported_and_never_counted(
    rates_domain_state: MacroDomainState,
) -> None:
    """The original defect, pinned where an operator actually reads it.

    The rates scenario carries a market-implied path, so the term is emitted; its own
    text promises it "contributes no confidence", and this is the assertion that keeps
    the promise machine-readable.
    """
    shadow = rates_domain_state.reason("market_path_is_a_shadow")
    assert shadow is not None, "the scenario's market-implied path should emit it"
    assert shadow.kind == "informational"
    # The value stays 0 on purpose -- the term is a marker, not a measurement. What was
    # wrong was calling zero a multiplicand, not the zero.
    assert shadow.value == Decimal(0)
    assert rates_domain_state.confidence > Decimal(0), (
        "a third-party shadow being present must not zero the state's confidence"
    )
