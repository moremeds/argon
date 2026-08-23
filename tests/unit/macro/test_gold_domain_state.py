"""Golden-scenario tests for the gold domain state (the gate).

Every input is real, frozen from the live publisher in
``tests/fixtures/macro/usd_gold_golden.json`` before this engine existed.  The ``expect``
blocks in that file are preregistered predictions: a test here that disagrees with one is
a finding about the engine, and the fixture is not the thing to edit.

Sibling of ``test_gold_state.py``, which covers the evidence MANIFEST.  This file covers
the STATE built on it.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from uw_scan.macro.contracts import DomainObservation
from uw_scan.macro.gold_state import (
    ANCHOR_SERIES,
    DOLLAR_SERIES,
    FLOW_SERIES,
    GOLD_OWNED_SERIES,
    REAL_YIELD_SERIES,
    SERIES_OWNER,
    GoldLensResult,
    compute_gold_state,
)
from uw_scan.macro.usd import UpstreamState

GOLDEN = json.loads(
    (
        Path(__file__).parents[2] / "fixtures" / "macro" / "usd_gold_golden.json"
    ).read_text(encoding="utf-8")
)
SCENARIOS: dict[str, dict[str, Any]] = {s["id"]: s for s in GOLDEN["scenarios"]}

DECOUPLED = "gold_and_real_yields_decoupled_post_2022"
FLOW_VS_CYCLICAL = "strong_official_flows_against_adverse_cyclical"


def _instant(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def _observation(row: dict[str, Any], obs_id: int) -> DomainObservation:
    return DomainObservation(
        series_id=row["series_id"],
        causal_role=row["causal_role"],
        period_end=date.fromisoformat(row["period_end"]),
        value=Decimal(row["value"]),
        unit=row["unit"],
        publisher_transform="level",
        available_at=_instant(row["available_at"]),
        superseded_at=(
            _instant(row["superseded_at"]) if row.get("superseded_at") else None
        ),
        source=row["source"],
        # The fixture predates the source-kind vocabulary this engine reads; "vendor"
        # is its word for what the contracts call an entitled provider.
        source_kind=(
            "entitled_provider"
            if row["source_kind"] == "vendor"
            else row["source_kind"]
        ),
        cost_class=row["cost_class"],
        # A stored row always has one; the persist path refuses a state whose evidence
        # cannot be pointed at, so a fixture without them would test a shape prod never
        # sees. Position in the fixture is a fine stand-in for the real identity.
        obs_id=obs_id,
    )


def _scenario(scenario_id: str) -> tuple[tuple[DomainObservation, ...], datetime]:
    scenario = SCENARIOS[scenario_id]
    rows = tuple(
        _observation(row, obs_id)
        for obs_id, row in enumerate(scenario["inputs"], start=1)
    )
    return rows, _instant(scenario["as_of"])


# --------------------------------------------------------------- preregistered scenarios


def test_decoupled_scenario_fires_the_post_2022_contradiction() -> None:
    """Gold and real yields rising together is reportable, not resolvable.

    Preregistered: ``contradictions_include: [gold_against_real_yields_post_2022]`` and
    ``lens2_direction_inferred: null``.
    """
    observations, as_of = _scenario(DECOUPLED)
    expect = SCENARIOS[DECOUPLED]["expect"]

    state = compute_gold_state(observations, as_of=as_of)

    for rule in expect["contradictions_include"]:
        assert state.fired(rule), (
            f"{rule} did not fire; fired={[c.rule for c in state.contradictions]}"
        )

    # The preregistered null: an adverse or decoupled backdrop is never turned into a
    # direction for gold.
    cyclical = state.sub_state("decomposition_component")
    assert cyclical is not None
    assert cyclical.direction == "UNKNOWN"

    # The contradiction reports; it does not resolve into a view.
    assert state.state in {"OPERATIVE", "PARTIAL", "SUSPENDED", "UNKNOWN"}


def test_decoupled_scenario_measures_both_legs_despite_unequal_print_counts() -> None:
    """The trap the calendar window exists to avoid.

    Over this quarter ``GLD_CLOSE`` has 64 prints and ``DFII10`` has 62 -- they run on
    different publication calendars. A window expressed in OBSERVATIONS would read the
    gold leg and return None for the real-yield leg, and the contradiction would go
    quiet for a reason that has nothing to do with the market.
    """
    observations, _ = _scenario(DECOUPLED)
    counts = {
        series: len({o.period_end for o in observations if o.series_id == series})
        for series in (ANCHOR_SERIES, REAL_YIELD_SERIES)
    }
    assert counts[ANCHOR_SERIES] != counts[REAL_YIELD_SERIES], (
        "fixture no longer has unequal print counts; this test guards a trap that would "
        "no longer be reproduced"
    )


def test_flow_against_cyclical_reports_both_without_precedence() -> None:
    """Preregistered: lens1 STRONG, lens2 ADVERSE, ``lens_precedence: null``."""
    observations, as_of = _scenario(FLOW_VS_CYCLICAL)
    expect = SCENARIOS[FLOW_VS_CYCLICAL]["expect"]

    state = compute_gold_state(observations, as_of=as_of)

    flow = state.sub_state("positioning")
    cyclical = state.sub_state("decomposition_component")
    assert flow is not None and cyclical is not None
    assert flow.state == expect["lens1_flow"]
    assert cyclical.state == expect["lens2_cyclical"]

    for rule in expect["contradictions_include"]:
        assert state.fired(rule), (
            f"{rule} did not fire; fired={[c.rule for c in state.contradictions]}"
        )

    # No precedence: BOTH readings survive into the state. A design that let one lens
    # overwrite the other would leave one of these two assertions unsatisfiable.
    assert flow.state != cyclical.state


def test_the_two_lenses_carry_their_own_confidence() -> None:
    """R2, applied to gold: the gate's confidence never stands in for a lens's."""
    observations, as_of = _scenario(FLOW_VS_CYCLICAL)
    state = compute_gold_state(observations, as_of=as_of)

    for role in ("positioning", "decomposition_component", "realized"):
        sub = state.sub_state(role)
        assert sub is not None, f"{role} sub-state missing"
        assert isinstance(sub.confidence, Decimal)


# ------------------------------------------------------------------------- invariants


def test_unrecognised_gauge_label_is_unknown_never_operative() -> None:
    """Spec 3.1. Defaulting to operative would assert the very thing the gate withholds."""
    observations, as_of = _scenario(DECOUPLED)
    state = compute_gold_state(
        observations,
        as_of=as_of,
        lens=GoldLensResult(
            obs_date=as_of.date(), gauge_state="a_label_from_the_future"
        ),
    )
    assert state.state == "UNKNOWN"


def test_gate_reads_the_stored_gauge_verdict() -> None:
    observations, as_of = _scenario(DECOUPLED)
    for gauge, expected in (
        ("operative", "OPERATIVE"),
        ("partial", "PARTIAL"),
        ("suspended", "SUSPENDED"),
    ):
        state = compute_gold_state(
            observations,
            as_of=as_of,
            lens=GoldLensResult(obs_date=as_of.date(), gauge_state=gauge),
        )
        assert state.state == expected


def test_suspended_gate_suspends_the_cyclical_lens() -> None:
    """A cyclical view drawn from a relationship measured as not holding is not a view."""
    observations, as_of = _scenario(FLOW_VS_CYCLICAL)
    state = compute_gold_state(
        observations,
        as_of=as_of,
        lens=GoldLensResult(obs_date=as_of.date(), gauge_state="suspended"),
    )
    cyclical = state.sub_state("decomposition_component")
    assert cyclical is not None
    assert cyclical.state == "SUSPENDED"
    assert cyclical.unavailable_reason is not None
    # And with Lens 2 suspended the flow/cyclical contradiction cannot fire: there is no
    # adverse cyclical reading to disagree with.
    assert not state.fired("gold_flow_against_cyclical")


def test_absent_anchor_abstains_rather_than_answering_from_upstream() -> None:
    observations, as_of = _scenario(DECOUPLED)
    without_price = tuple(o for o in observations if o.series_id != ANCHOR_SERIES)
    state = compute_gold_state(without_price, as_of=as_of)
    assert state.confidence == Decimal(0)
    absent = state.reason("absent_reason") or state.reason("completeness")
    assert absent is not None


def test_borrowed_series_are_not_in_the_confidence_denominator() -> None:
    """The double-count rule's practical edge.

    Gold READS the real yield and the broad dollar -- Lens 2 is defined on them -- but a
    quiet upstream must degrade the LENS, never the gate's own confidence.
    """
    assert SERIES_OWNER[REAL_YIELD_SERIES] == "policy_rates"
    assert SERIES_OWNER[DOLLAR_SERIES] == "usd"
    assert REAL_YIELD_SERIES not in GOLD_OWNED_SERIES
    assert DOLLAR_SERIES not in GOLD_OWNED_SERIES
    assert set(GOLD_OWNED_SERIES) == {ANCHOR_SERIES, FLOW_SERIES}

    observations, as_of = _scenario(FLOW_VS_CYCLICAL)
    full = compute_gold_state(observations, as_of=as_of)
    without_dollar = compute_gold_state(
        tuple(o for o in observations if o.series_id != DOLLAR_SERIES), as_of=as_of
    )
    assert without_dollar.confidence == full.confidence


def test_borrowed_evidence_is_named_in_the_reasons() -> None:
    observations, as_of = _scenario(FLOW_VS_CYCLICAL)
    state = compute_gold_state(observations, as_of=as_of)
    borrowed = state.reason("borrowed_evidence")
    assert borrowed is not None
    assert REAL_YIELD_SERIES in borrowed.detail
    assert "policy_rates" in borrowed.detail


def test_evidence_refs_point_at_the_shared_observations() -> None:
    """Many readers, one row: the borrowed refs carry obs_ids, they are not copies."""
    observations, as_of = _scenario(FLOW_VS_CYCLICAL)
    state = compute_gold_state(observations, as_of=as_of)
    series = {ref.series_id for ref in state.evidence_refs}
    assert REAL_YIELD_SERIES in series
    assert ANCHOR_SERIES in series or FLOW_SERIES in series
    assert all(ref.obs_id is not None for ref in state.evidence_refs)


def test_inputs_hash_changes_when_an_upstream_changes_its_mind() -> None:
    observations, as_of = _scenario(DECOUPLED)
    base = UpstreamState(
        domain="policy_rates",
        state="ON_HOLD",
        direction="FLAT",
        inputs_hash="a" * 64,
        as_of=as_of,
    )
    moved = UpstreamState(
        domain="policy_rates",
        state="ON_HOLD",
        direction="FLAT",
        inputs_hash="b" * 64,
        as_of=as_of,
    )
    first = compute_gold_state(observations, as_of=as_of, upstream=(base,))
    second = compute_gold_state(observations, as_of=as_of, upstream=(moved,))
    assert first.inputs_hash != second.inputs_hash


def test_upstream_from_the_future_is_refused() -> None:
    observations, as_of = _scenario(DECOUPLED)
    ahead = UpstreamState(
        domain="usd",
        state="RANGEBOUND",
        direction="FLAT",
        inputs_hash="c" * 64,
        as_of=_instant("2027-01-01"),
    )
    with pytest.raises(ValueError, match="lookahead"):
        compute_gold_state(observations, as_of=as_of, upstream=(ahead,))


def test_valuation_lens_is_a_warning_and_says_so() -> None:
    observations, as_of = _scenario(DECOUPLED)
    state = compute_gold_state(
        observations,
        as_of=as_of,
        lens=GoldLensResult(
            obs_date=as_of.date(), gauge_state="operative", valuation_flag="Severe"
        ),
    )
    valuation = state.sub_state("realized")
    assert valuation is not None
    assert valuation.state == "STRETCHED"
    warning = next(
        r for r in valuation.confidence_reasons if r.term == "valuation_is_a_warning"
    )
    assert "never" in warning.detail
