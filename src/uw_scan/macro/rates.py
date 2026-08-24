"""Point-in-time policy and rates state.

Two rules shape this module, and both are refusals.

**The four policy paths never merge.** What the committee has done, what it projects,
what dealers expect and what contracts price are four different facts with four
different publishers.  At authoring time the SEP median for end-2026 is 3.80 and the
market-implied rate is 3.875; their average, 3.8375, is not on the SEP's eighth-point
dot grid, no participant projected it and no contract prices it.  It is an artifact of
averaging -- and exactly the number a composite would have reported.

**Slope is shape, not term premium.** Curve steepness is reported as steepness.  The
words "term premium" belong only to the Cleveland Fed's estimated model, which is a
model output with its own vintage and its own uncertainty, not a spread between two
traded yields.

Design: ``docs/superpowers/specs/2026-08-18-inflation-rates-state-design.md``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from uw_scan.models.macro import PolicyPath, PolicyPathKind

from .confidence import compute_confidence
from .contracts import (
    CausalRole,
    ConfidenceTerm,
    Direction,
    DomainObservation,
    EvidenceRef,
    FactorState,
    MacroDomainState,
    MacroSubState,
    compute_inputs_hash,
    freshness_for,
)
from .rates_sub_states import build_sub_states
from .rates_rules import (
    YieldAttribution,
    attribute_nominal_change,
    forward_spreads,
    market_contradictions,
    horizon_years,
    policy_contradictions,
    rates_velocity,
    year_end_rate,
)

#: Bumped when the shared confidence engine's revision penalty changed divisor, from
#: every factor consumed to the required set its numerator was already drawn from.  The
#: state LABEL is untouched, but confidence is published on the state record and a
#: reader comparing it across this line would be comparing two arithmetics.  Engine
#: version is the selector that keeps them apart; stored rates/1 states stay readable.
RATES_ENGINE_VERSION = "rates/2"

RatesStateLabel = Literal["EASING", "ON_HOLD", "TIGHTENING", "INDETERMINATE"]

#: Load-bearing for the POLICY state, which is what ``state`` describes.  Supply,
#: positioning and plumbing are reported factors with their own freshness, but none of
#: them bears on whether the committee cut, held or hiked -- so their absence must not
#: erase a published fact.  The market path is excluded deliberately: it is a
#: third-party shadow and never load-bearing unless a caller demands it.
POLICY_REQUIRED: tuple[PolicyPathKind, ...] = (
    "actual",
    "committee_projection",
    "dealer_expectations",
)
FORWARD_KINDS: tuple[PolicyPathKind, ...] = (
    "committee_projection",
    "dealer_expectations",
    "market_implied",
)
#: Forward paths whose disagreement is allowed to set ``direction``.  A shadow may be
#: reported and may be measured against the others; it may not outvote them.
LOAD_BEARING_FORWARD: tuple[PolicyPathKind, ...] = (
    "committee_projection",
    "dealer_expectations",
)

_ACTION_STATE: dict[str, RatesStateLabel] = {
    "hold": "ON_HOLD",
    "cut": "EASING",
    "hike": "TIGHTENING",
    "raise": "TIGHTENING",
    "lower": "EASING",
}


@dataclass(frozen=True)
class RatesParameters:
    """Versioned thresholds, hashed with the evidence rather than hidden in constants."""

    version: str = "rates/2"
    #: One eighth of a point -- the finest increment an SEP dot can express, and half
    #: the smallest move the committee actually makes.  Anything coarser would round a
    #: real projected lean to "flat".
    direction_threshold_bps: Decimal = Decimal("12.5")
    #: Half a policy move.  Below this the paths are saying the same thing in different
    #: units of precision; above it they are describing different worlds.
    path_disagreement_bps: Decimal = Decimal("25")
    #: Inflation compensation that moved by less than one SEP increment has not
    #: confirmed anything about the inflation regime.
    breakeven_flat_bps: Decimal = Decimal("10")
    #: A nominal move worth explaining: one policy move.
    material_nominal_move_bps: Decimal = Decimal("25")
    #: Quarters of new-issue auction sizes that set the "elevated" comparison.
    supply_baseline_quarters: int = 4
    #: Applies ONLY to the Cleveland model against the traded yield; see the module
    #: docstring on why an intra-model sum cannot fail.  Calibrated, not picked: the
    #: modelled and traded 10y normally differ by 41bp (63bp since 2016), so a 25bp
    #: tolerance would fire on 66.9% of months and mean nothing.  85bp is the post-2016
    #: p90 and fires on 11 of 332 months, all of them in the 2022 repricing.
    #: Measured: docs/research/2026-08-18-mc2-decomposition-residual/
    decomposition_tolerance_bps: Decimal = Decimal("85")
    contradiction_penalty_each: Decimal = Decimal("0.15")
    contradiction_penalty_cap: Decimal = Decimal("0.60")
    freshness_decay_multiple: Decimal = Decimal("3")
    policy_path_cadence_days: int = 120
    market_series_cadence_days: int = 4
    #: Per role, because a market factor's cadence is its PUBLISHER's, not the domain's.
    #: These were one value -- the 120-day policy-path cadence -- until the golden
    #: staleness scenario showed what that costs: a COT report four months past its
    #: weekly release read as perfectly fresh, because 120 days is seventeen weeks.
    #: A freshness term that cannot detect a publisher going quiet is decoration.
    supply_cadence_days: int = 92
    positioning_cadence_days: int = 7

    def as_record(self) -> dict[str, Any]:
        return {
            key: (format(value, "f") if isinstance(value, Decimal) else value)
            for key, value in sorted(asdict(self).items())
        }


DEFAULT_RATES_PARAMETERS = RatesParameters()


def compute_rates_state(
    paths: Iterable[PolicyPath],
    *,
    as_of: datetime,
    observations: Iterable[DomainObservation] = (),
    parameters: RatesParameters = DEFAULT_RATES_PARAMETERS,
    attribution: YieldAttribution | None = None,
    prior_state: MacroDomainState | None = None,
) -> MacroDomainState:
    """Assemble the rates state from independent paths and market factors."""
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")

    by_kind: dict[PolicyPathKind, PolicyPath] = {}
    for path in paths:
        if path.available_at > as_of:
            continue
        if path.kind in by_kind:
            raise ValueError(f"duplicate policy path kind: {path.kind}")
        by_kind[path.kind] = path

    eligible = tuple(obs for obs in observations if obs.is_known_on(as_of))
    factors = _policy_factors(
        by_kind, as_of=as_of, parameters=parameters
    ) + _market_factors(eligible, as_of=as_of, parameters=parameters)
    sub_states = build_sub_states(
        eligible,
        factors,
        as_of=as_of,
        supply_baseline_quarters=parameters.supply_baseline_quarters,
        cadence_by_role=_CADENCE_BY_ROLE(parameters),
        freshness_decay_multiple=parameters.freshness_decay_multiple,
    )
    horizon, spreads = forward_spreads(by_kind, not_before=as_of.year)
    state, unread_action = _policy_state(by_kind.get("actual"))
    direction = _direction(by_kind, as_of=as_of, parameters=parameters)
    contradictions = policy_contradictions(
        by_kind,
        eligible,
        spreads=spreads,
        state=state,
        direction=direction,
        attribution=attribution,
        parameters=parameters,
    ) + market_contradictions(
        eligible,
        sub_states,
        state=state,
        prior_state=prior_state,
        parameters=parameters,
    )

    # Only the required ids count. Filtering on `_POLICY_SERIES_IDS` instead would let
    # the market shadow stand in for an absent dealer path and report full coverage --
    # the exact substitution this domain exists to refuse.
    required_ids = tuple(_POLICY_SERIES_IDS[kind] for kind in POLICY_REQUIRED)
    load_bearing = tuple(
        factor for factor in factors if factor.series_id in set(required_ids)
    )
    confidence, reasons = compute_confidence(
        load_bearing,
        required_series=required_ids,
        contradictions=contradictions,
        contradiction_penalty_each=parameters.contradiction_penalty_each,
        contradiction_penalty_cap=parameters.contradiction_penalty_cap,
        prior_state=prior_state,
        absent_reason=(
            None
            if "actual" in by_kind
            else "no FOMC target-range release was available at as_of; the policy "
            "state abstains rather than inferring what the committee did"
        ),
    )
    reasons = reasons + _coverage_notes(by_kind, factors) + _sub_state_notes(sub_states)

    used = tuple(sorted(eligible, key=lambda obs: (obs.series_id, obs.period_end)))
    return MacroDomainState(
        domain="policy_rates",
        state=state,
        direction=direction,
        velocity=rates_velocity(by_kind, horizon, spreads, attribution),
        confidence=confidence,
        confidence_reasons=reasons,
        contradictions=contradictions,
        factors=factors,
        evidence_refs=_policy_evidence(by_kind)
        + tuple(
            EvidenceRef(
                series_id=obs.series_id,
                period_end=obs.period_end,
                causal_role=obs.causal_role,
                available_at=obs.available_at,
                obs_id=obs.obs_id,
                artifact_id=obs.artifact_id,
            )
            for obs in used
        ),
        engine_version=RATES_ENGINE_VERSION,
        inputs_hash=compute_inputs_hash(
            engine_version=RATES_ENGINE_VERSION,
            parameters={
                **parameters.as_record(),
                "policy_paths": sorted(
                    f"{kind}:{path.source_record_id}:{path.available_at.isoformat()}"
                    for kind, path in by_kind.items()
                ),
            },
            observations=used,
        ),
        as_of=as_of,
        notes=(
            "curve steepness is reported as steepness; the only term-premium figure in "
            "this domain comes from the Cleveland Fed's estimated model",
        )
        + ((unread_action,) if unread_action else ()),
        sub_states=sub_states,
    )


def _sub_state_notes(
    sub_states: tuple[MacroSubState, ...],
) -> tuple[ConfidenceTerm, ...]:
    """Each sub-state's own confidence, surfaced beside the policy number.

    Informational on purpose: none of these is in the policy confidence product, and R2
    is the reason. What they prevent is a surface rendering one number above a panel
    holding both -- a reader cannot tell from a single 1.00 whether the positioning read
    behind it is fresh or four months stale.
    """
    return tuple(
        ConfidenceTerm(
            term=f"sub_state_confidence:{item.role}",
            value=item.confidence,
            detail=(
                f"{item.role} is {item.state} with its own confidence "
                f"{item.confidence:.2f} over {len(item.series_ids)} series"
                + (f"; {item.unavailable_reason}" if item.unavailable_reason else "")
            ),
            kind="informational",
        )
        for item in sub_states
    )


#: Each path gets a stable factor id so a state can be reconstructed and diffed.
_POLICY_SERIES_IDS: dict[PolicyPathKind, str] = {
    "actual": "FOMC_TARGET_RANGE",
    "committee_projection": "SEP_FEDERAL_FUNDS_RATE",
    "dealer_expectations": "NYFED_SME_FEDERAL_FUNDS_RATE",
    "market_implied": "MARKET_IMPLIED_FEDERAL_FUNDS_RATE",
}
_POLICY_ROLES: dict[PolicyPathKind, CausalRole] = {
    "actual": "policy_actual",
    "committee_projection": "policy_committee",
    "dealer_expectations": "policy_dealer",
    "market_implied": "policy_market_shadow",
}


def _policy_evidence(
    by_kind: dict[PolicyPathKind, PolicyPath],
) -> tuple[EvidenceRef, ...]:
    """Cite the policy releases, not only the market series.

    ``state`` is read off the FOMC's own target range, so a lineage listing only DGS10
    and its siblings would omit the one input the answer actually turned on.  A path
    whose stored observation carries no id is skipped rather than cited as a headless
    reference: it would name evidence nobody can retrieve.
    """
    out: list[EvidenceRef] = []
    for kind, path in sorted(by_kind.items()):
        for ref in path.evidence_refs:
            out.append(
                EvidenceRef(
                    series_id=_POLICY_SERIES_IDS[kind],
                    period_end=ref.period_end,
                    causal_role=_POLICY_ROLES[kind],
                    available_at=ref.available_at,
                    obs_id=ref.obs_id,
                    artifact_id=ref.artifact_id,
                )
            )
    return tuple(out)


def _policy_factors(
    by_kind: dict[PolicyPathKind, PolicyPath],
    *,
    as_of: datetime,
    parameters: RatesParameters,
) -> tuple[FactorState, ...]:
    out: list[FactorState] = []
    for kind, path in by_kind.items():
        anchor = path.points[0]
        age_days = (as_of.date() - path.available_at.date()).days
        out.append(
            FactorState(
                name=f"{_POLICY_ROLES[kind]}:{path.source}",
                causal_role=_POLICY_ROLES[kind],  # type: ignore[arg-type]
                series_id=_POLICY_SERIES_IDS[kind],
                period_end=(anchor.horizon_date or path.available_at.date()),
                value=anchor.rate_percent,
                unit="percent",
                direction="UNKNOWN",
                change_over_window=None,
                available_at=path.available_at,
                age_days=age_days,
                freshness=freshness_for(
                    age_days,
                    parameters.policy_path_cadence_days,
                    parameters.freshness_decay_multiple,
                ),
                quality_status="valid",
                source=path.source,
                source_kind=path.source_kind,
            )
        )
    return tuple(out)


def _CADENCE_BY_ROLE(parameters: RatesParameters) -> dict[CausalRole, int]:
    """How often each role's publisher is expected to speak.

    A role missing from this table falls back to the policy-path cadence, which is the
    longest and therefore the most forgiving -- an unknown role should not be marked
    stale by a cadence nobody declared for it.
    """
    return {
        "curve": parameters.market_series_cadence_days,
        "decomposition_component": parameters.market_series_cadence_days,
        "plumbing": parameters.market_series_cadence_days,
        "supply": parameters.supply_cadence_days,
        "positioning": parameters.positioning_cadence_days,
    }


def _market_factors(
    observations: tuple[DomainObservation, ...],
    *,
    as_of: datetime,
    parameters: RatesParameters,
) -> tuple[FactorState, ...]:
    """One factor per market series, each carrying its own freshness.

    Supply, positioning and plumbing stay separate rather than folding into a single
    "technicals" score: they move on different clocks and for different reasons, and a
    blended score cannot say which of them is stale.
    """
    latest: dict[str, DomainObservation] = {}
    for obs in observations:
        current = latest.get(obs.series_id)
        if current is None or obs.period_end > current.period_end:
            latest[obs.series_id] = obs
    out: list[FactorState] = []
    for series_id, obs in sorted(latest.items()):
        age_days = (as_of.date() - obs.available_at.date()).days
        cadence = _CADENCE_BY_ROLE(parameters).get(
            obs.causal_role, parameters.policy_path_cadence_days
        )
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
                freshness=freshness_for(
                    age_days, cadence, parameters.freshness_decay_multiple
                ),
                quality_status=obs.quality_status,
                source=obs.source,
                source_kind=obs.source_kind,
            )
        )
    return tuple(out)


def _policy_state(actual: PolicyPath | None) -> tuple[RatesStateLabel, str | None]:
    """What the committee has done, which is a published fact rather than a view.

    Returns the label and, when the release said something this engine could not read,
    a note saying so.  An action word we do not recognise is not the same as no action
    word: falling silently through to the rate difference would report a state as if it
    had been read off the committee's own sentence when in fact that sentence was
    discarded.  The statement parser's own vocabulary is closed -- Hold, Hike, Cut --
    so this can only fire on a producer that has started saying something new, which is
    exactly when the operator needs to hear about it.
    """
    if actual is None:
        return "INDETERMINATE", None
    points = sorted(
        actual.points, key=lambda point: point.horizon_date or date.min, reverse=True
    )
    # ``point.action`` is truthy for a whitespace-only string, whose ``split()`` is
    # empty -- indexing that was a crash, and a blank action is not a stated one.
    stated = next(
        (point.action.strip() for point in points if (point.action or "").strip()),
        None,
    )
    unread: str | None = None
    if stated is not None:
        mapped = _ACTION_STATE.get(stated.lower().split()[0])
        if mapped is not None:
            return mapped, None
        unread = (
            f"{actual.source} stated the action as {stated!r}, which this engine does "
            "not recognise; the state below was inferred from the target ranges instead"
        )
    if len(points) >= 2:
        move = points[0].rate_percent - points[1].rate_percent
        if move > 0:
            return "TIGHTENING", unread
        if move < 0:
            return "EASING", unread
        return "ON_HOLD", unread
    return "INDETERMINATE", unread


def _direction(
    by_kind: dict[PolicyPathKind, PolicyPath],
    *,
    as_of: datetime,
    parameters: RatesParameters,
) -> Direction:
    """Where the load-bearing forward paths agree rates are going.

    The market shadow is excluded from this vote on purpose.  It is reported, and it is
    measured against the others for disagreement, but a third-party estimate must not be
    able to move an official reading to UNKNOWN on its own.
    """
    actual = by_kind.get("actual")
    if actual is None:
        return "UNKNOWN"
    anchor = actual.points[0].rate_percent
    leans: set[Direction] = set()
    for kind in LOAD_BEARING_FORWARD:
        path = by_kind.get(kind)
        if path is None:
            continue
        for year in horizon_years(path, not_before=as_of.year):
            rate = year_end_rate(path, year)
            if rate is None:
                continue
            gap = (rate - anchor) * 100
            if gap >= parameters.direction_threshold_bps:
                leans.add("RISING")
            elif gap <= -parameters.direction_threshold_bps:
                leans.add("FALLING")
            else:
                leans.add("FLAT")
            break
    if not leans:
        return "UNKNOWN"
    return leans.pop() if len(leans) == 1 else "UNKNOWN"


def _coverage_notes(
    by_kind: dict[PolicyPathKind, PolicyPath], factors: tuple[FactorState, ...]
) -> tuple[ConfidenceTerm, ...]:
    """Name what is absent, path by path and factor by factor.

    A missing path is never filled by the other three and never counted as a neutral
    vote; it is reported as missing, and the confidence it would have supported is not
    awarded.  The market shadow is reported separately because its presence must not
    raise confidence -- it is a third-party estimate, not evidence.
    """
    out: list[ConfidenceTerm] = []
    missing = [kind for kind in POLICY_REQUIRED if kind not in by_kind]
    if missing:
        out.append(
            ConfidenceTerm(
                term="policy_paths_absent",
                value=Decimal(len(missing)),
                detail=(
                    f"no PIT-eligible release for: {', '.join(missing)}; each absence "
                    "lowers confidence and is never filled from another path"
                ),
            )
        )
    if "market_implied" in by_kind:
        out.append(
            ConfidenceTerm(
                term="market_path_is_a_shadow",
                value=Decimal(0),
                detail=(
                    f"{by_kind['market_implied'].source} is a third-party shadow; it is "
                    "reported and compared, but contributes no confidence"
                ),
            )
        )
    roles = {factor.causal_role for factor in factors}
    absent_market = [
        role
        for role in (
            "curve",
            "decomposition_component",
            "supply",
            "positioning",
            "plumbing",
        )
        if role not in roles
    ]
    # Emitted at zero too, deliberately.  A term that disappears when healthy gives a
    # reader nothing to notice when it comes back: "no market_factors_absent line" and
    # "this surface never had one" are the same sight. Reported as 0, a regression to 1
    # is a visible change rather than the reappearance of a line nobody was watching.
    out.append(
        ConfidenceTerm(
            term="market_factors_absent",
            value=Decimal(len(absent_market)),
            detail=(
                (
                    f"no observations for: {', '.join(absent_market)}; these do not "
                    "gate the policy state but their sub-states are unavailable"
                )
                if absent_market
                else (
                    "every market role resolved to evidence; each publishes its own "
                    "sub-state confidence, and none of them gates the policy state"
                )
            ),
            # A COUNT of absent factor groups, not a multiplicand.  It is not in
            # the confidence product at all -- rendered as one, "3" reads as a
            # term that tripled the number it is only annotating.
            kind="informational",
        )
    )
    return tuple(out)


__all__ = [
    "DEFAULT_RATES_PARAMETERS",
    "RATES_ENGINE_VERSION",
    "RatesParameters",
    "RatesStateLabel",
    # Re-exported: the attribution primitives live with the rules that consume them,
    # but callers reach for them through the engine.
    "YieldAttribution",
    "attribute_nominal_change",
    "compute_rates_state",
]
