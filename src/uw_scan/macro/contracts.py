"""Contracts shared by the point-in-time macro domain engines.

A domain state answers four questions that a single score cannot: what regime we are
in, which way it is moving, how fast, and how much of that we actually know.  The last
one is the point.  A composite that renormalises over whichever inputs happened to
arrive reports full conviction from one populated group, so ``confidence`` here is a
function of knowledge -- coverage, freshness, quality, revisions, contradictions --
and never of how large the signal is.

These are plain frozen dataclasses rather than Pydantic models on purpose: they are the
engines' internal contract, computed before anything is persisted or served, and they
must stay cheap enough to build inside a tight scenario test.  The API surface is a
separate contract layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from uw_scan.macro_evidence import macro_artifact_content_identity
from uw_scan.models.macro import (
    ConfidenceTermKind,
    MacroCausalRole,
    MacroCostClass,
    MacroDirection,
    MacroDomain,
    MacroQualityStatus,
    MacroSourceKind,
)

Direction = MacroDirection

#: What an input *does* in a state, which is not what it measures.  A breakeven and a
#: survey are both about future inflation and are still different evidence, so the role
#: travels with the observation and the engine refuses to pool two unlike roles.
#: Defined in ``uw_scan.models.macro`` so the engine and the API contract cannot drift.
CausalRole = MacroCausalRole

#: How much a reading counts toward a state's quality term.  One table, shared by the
#: observation and the confidence engine: two copies drift, and the copy that drifts is
#: the one that silently prices an input the store meant to take out of service.  A
#: status outside this table raises rather than defaulting, because an unrecognised
#: quality label is exactly the thing that must not be quietly assigned a weight.
QUALITY_WEIGHT: dict[MacroQualityStatus, Decimal] = {
    "valid": Decimal("1.0"),
    "partial": Decimal("0.5"),
    "invalid": Decimal("0"),
    "quarantined": Decimal("0"),
}


@dataclass(frozen=True)
class DomainObservation:
    """One published value with the window during which it was the published value.

    ``superseded_at`` is exclusive: a vintage is in force over
    ``[available_at, superseded_at)``.  Without it, a replay returns every restatement
    a period ever had and silently prefers the newest -- which is reading today's
    number into the past.
    """

    series_id: str
    causal_role: CausalRole
    period_end: date
    value: Decimal
    unit: str
    publisher_transform: str
    available_at: datetime
    source: str
    source_kind: MacroSourceKind
    cost_class: MacroCostClass
    quality_status: MacroQualityStatus = "valid"
    superseded_at: datetime | None = None
    obs_id: int | None = None
    artifact_id: int | None = None

    def is_known_on(self, as_of: datetime) -> bool:
        return self.available_at <= as_of and (
            self.superseded_at is None or as_of < self.superseded_at
        )

    @property
    def quality_weight(self) -> Decimal:
        return QUALITY_WEIGHT[self.quality_status]


@dataclass(frozen=True)
class Velocity:
    """How fast, stated with its metric, unit and window -- never a bare number."""

    metric: str
    value: Decimal | None
    unit: str
    window_months: int
    unavailable_reason: str | None = None


@dataclass(frozen=True)
class FactorState:
    """One input's own sub-state, carrying its own freshness rather than inheriting one."""

    name: str
    causal_role: CausalRole
    series_id: str
    period_end: date
    value: Decimal
    unit: str
    direction: Direction
    change_over_window: Decimal | None
    available_at: datetime
    age_days: int
    freshness: Decimal
    quality_status: MacroQualityStatus
    source: str
    source_kind: MacroSourceKind


@dataclass(frozen=True)
class ConfidenceTerm:
    """One term behind a confidence number, with what drove it.

    Recorded per term so a confidence number can be argued with rather than believed.

    ``kind`` says how to read ``value``, because the terms are not all the same shape
    and a reader cannot tell from the number: 1.00 means "no drag" for a multiplicand
    and "full drag" for a penalty, and an informational term is not in the product at
    all -- ``market_factors_absent`` carries a COUNT of absent factor groups, so
    rendering it beside the others as "x3.00" invites reading it as a term that
    tripled the confidence. The producer knows which is which; naming it here is what
    stops every consumer from re-deriving it by matching on term strings.
    """

    term: str
    value: Decimal
    detail: str
    kind: ConfidenceTermKind = "multiplicand"


@dataclass(frozen=True)
class Contradiction:
    rule: str
    detail: str


@dataclass(frozen=True)
class EvidenceRef:
    """The exact observation a state stood on, so the state can be reconstructed."""

    series_id: str
    period_end: date
    causal_role: CausalRole
    available_at: datetime
    obs_id: int | None = None
    artifact_id: int | None = None


@dataclass(frozen=True)
class MacroSubState:
    """One causal role's own read, with its own confidence.

    A domain state answers one question; a sub-state answers a narrower one beside it.
    They are kept apart rather than folded together because their denominators differ:
    the rates policy state is gated by the three policy paths and nothing else, while a
    positioning read is gated by whether CFTC published. Sharing one confidence number
    would let either stand in for the other, which is the substitution
    ``macro/rates.py:169`` exists to refuse.

    ``state`` is a plain string rather than a shared Literal because the vocabularies are
    per role and not comparable -- ELEVATED is about issuance size and STRETCHED_LOW is a
    percentile of a position. A common enum would invite exactly the cross-role
    comparison the split is for. Every vocabulary includes ``UNKNOWN``, and never
    ``NEUTRAL``: absence is not a centred reading.
    """

    role: CausalRole
    state: str
    direction: Direction
    velocity: tuple[Velocity, ...]
    confidence: Decimal
    confidence_reasons: tuple[ConfidenceTerm, ...]
    series_ids: tuple[str, ...]
    latest_period_end: date | None = None
    unavailable_reason: str | None = None


@dataclass(frozen=True)
class MacroDomainState:
    domain: MacroDomain
    state: str
    direction: Direction
    velocity: tuple[Velocity, ...]
    confidence: Decimal
    confidence_reasons: tuple[ConfidenceTerm, ...]
    contradictions: tuple[Contradiction, ...]
    factors: tuple[FactorState, ...]
    evidence_refs: tuple[EvidenceRef, ...]
    engine_version: str
    inputs_hash: str
    as_of: datetime
    notes: tuple[str, ...] = field(default_factory=tuple)
    #: Per-role reads that sit BESIDE the domain state without gating it.
    sub_states: tuple[MacroSubState, ...] = field(default_factory=tuple)

    def sub_state(self, role: CausalRole) -> MacroSubState | None:
        return next((item for item in self.sub_states if item.role == role), None)

    def factor(self, series_id: str) -> FactorState | None:
        return next((f for f in self.factors if f.series_id == series_id), None)

    def fired(self, rule: str) -> bool:
        return any(item.rule == rule for item in self.contradictions)

    def reason(self, term: str) -> ConfidenceTerm | None:
        return next((r for r in self.confidence_reasons if r.term == term), None)


def clamp_unit(value: Decimal) -> Decimal:
    return min(Decimal(1), max(Decimal(0), value))


def freshness_for(age_days: int, cadence_days: int, decay_multiple: Decimal) -> Decimal:
    """1.0 while the publisher is on schedule, decaying to 0 at ``decay_multiple`` cadences.

    Age is measured from ``available_at``, not from ``period_end``.  A monthly series is
    normally read six weeks after the month it describes; penalising that would mark
    every monthly input permanently stale.  What staleness should detect is a publisher
    that has gone quiet past its own cadence.
    """
    if age_days <= cadence_days:
        return Decimal(1)
    limit = cadence_days * decay_multiple
    if Decimal(age_days) >= limit:
        return Decimal(0)
    return clamp_unit((limit - Decimal(age_days)) / (limit - Decimal(cadence_days)))


def compute_inputs_hash(
    *,
    engine_version: str,
    parameters: dict[str, Any],
    observations: tuple[DomainObservation, ...],
) -> str:
    """Identify a state by the parameters AND the exact observations that produced it.

    Thresholds are hashed alongside the data because they are inputs.  A threshold moved
    in a module constant would otherwise silently change every state while leaving the
    identity that is supposed to detect the change untouched.
    """
    record = {
        "engine_version": engine_version,
        "observations": sorted(
            (
                {
                    "available_at": obs.available_at.isoformat(),
                    "period_end": obs.period_end.isoformat(),
                    "series_id": obs.series_id,
                    "unit": obs.unit,
                    "value": format(obs.value.normalize(), "f"),
                }
                for obs in observations
            ),
            key=lambda item: (item["series_id"], item["period_end"]),
        ),
        "parameters": parameters,
    }
    content_hash, _length = macro_artifact_content_identity(raw_json=record)
    return content_hash
