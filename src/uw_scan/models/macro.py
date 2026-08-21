"""Shared point-in-time macro evidence contracts."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import AwareDatetime, Field, field_validator, model_validator

from uw_scan.macro_evidence import (
    macro_artifact_content_identity,
    macro_observation_content_hash,
)

from ._base import _preserve_public_module, _UwBase

MacroDomain = Literal["inflation", "policy_rates", "usd", "gold", "cross_domain"]
MacroSourceKind = Literal[
    "official",
    "first_party_publisher",
    "entitled_provider",
    "third_party_shadow",
    "mock",
    "static",
    "demo",
]
MacroQualityStatus = Literal["valid", "invalid", "partial", "quarantined"]
MacroCostClass = Literal[
    "free_official",
    "free_publisher",
    "already_entitled",
    "free_third_party_shadow",
    "paid_authorized",
]
MacroFrequency = Literal[
    "daily", "weekly", "monthly", "quarterly", "annual", "event", "irregular"
]
PolicyPathKind = Literal[
    "actual", "committee_projection", "dealer_expectations", "market_implied"
]
PolicyPathDelayStatus = Literal["known", "unknown", "not_applicable"]
#: Defined here rather than in ``uw_scan.macro.contracts`` because that module already
#: imports from this one; a second copy of either literal would drift the moment a role
#: is added, and the drift would only surface as a serialization failure.
MacroDirection = Literal["RISING", "FALLING", "FLAT", "UNKNOWN"]
MacroCausalRole = Literal[
    "realized",
    "breadth",
    "stickiness",
    "expectations_survey",
    "expectations_market",
    "policy_actual",
    "policy_committee",
    "policy_dealer",
    "policy_market_shadow",
    "curve",
    "decomposition_component",
    "supply",
    "positioning",
    "plumbing",
]
#: ``stale`` means only that no newer state has been computed; it says nothing about the
#: publishers, which carry their own per-factor freshness inside ``confidence_reasons``.
MacroStateFreshness = Literal["fresh", "stale"]


class MacroSourceArtifact(_UwBase):
    artifact_id: int | None = None
    source: str
    source_kind: MacroSourceKind
    source_record_id: str
    source_url: str | None = None
    published_at: AwareDatetime | None = None
    available_at: AwareDatetime
    retrieved_at: AwareDatetime
    last_seen_at: AwareDatetime
    content_hash: str
    parser_version: str
    quality_status: MacroQualityStatus
    cost_class: MacroCostClass
    media_type: str
    content_length: int
    #: True when the payload states when each value it carries was first published,
    #: rather than being that publication.  An ALFRED series response is one; an FOMC
    #: statement is not.  It changes which availability bound the store enforces, so it
    #: is declared by the adapter that knows the shape rather than inferred downstream.
    vintage_bearing: bool = False
    raw_json: dict[str, Any] | list[Any] | None = None
    raw_text: str | None = None
    raw_bytes: bytes | None = None

    @field_validator("content_hash")
    @classmethod
    def _sha256_hash(cls, value: str) -> str:
        return _validate_sha256(value)

    @model_validator(mode="after")
    def _one_raw_representation(self) -> "MacroSourceArtifact":
        if (
            sum(
                value is not None
                for value in (self.raw_json, self.raw_text, self.raw_bytes)
            )
            != 1
        ):
            raise ValueError("exactly one raw payload representation is required")
        if self.published_at is not None and self.published_at > self.available_at:
            raise ValueError("published_at must not follow available_at")
        if self.retrieved_at > self.last_seen_at:
            raise ValueError("retrieved_at must not follow last_seen_at")
        actual_hash, actual_length = macro_artifact_content_identity(
            raw_json=self.raw_json,
            raw_text=self.raw_text,
            raw_bytes=self.raw_bytes,
        )
        if self.content_hash != actual_hash:
            raise ValueError("content_hash does not match the raw artifact")
        if self.content_length != actual_length:
            raise ValueError("content_length does not match the raw artifact")
        return self


class MacroObservation(_UwBase):
    obs_id: int | None = None
    artifact_id: int
    domain: MacroDomain
    series_id: str
    period_end: date
    frequency: MacroFrequency
    unit: str
    value_numeric: Decimal | None = None
    value_text: str | None = None
    value_json: dict[str, Any] | list[Any] | None = None
    source: str
    source_record_id: str
    published_at: AwareDatetime | None = None
    available_at: AwareDatetime
    first_observed_at: AwareDatetime
    last_seen_at: AwareDatetime
    content_hash: str
    parser_version: str
    quality_status: MacroQualityStatus
    cost_class: MacroCostClass

    @field_validator("content_hash")
    @classmethod
    def _sha256_hash(cls, value: str) -> str:
        return _validate_sha256(value)

    @model_validator(mode="after")
    def _one_typed_value(self) -> "MacroObservation":
        if (
            sum(
                value is not None
                for value in (self.value_numeric, self.value_text, self.value_json)
            )
            != 1
        ):
            raise ValueError("exactly one typed observation value is required")
        if self.published_at is not None and self.published_at > self.available_at:
            raise ValueError("published_at must not follow available_at")
        if self.first_observed_at > self.last_seen_at:
            raise ValueError("first_observed_at must not follow last_seen_at")
        if self.content_hash != macro_observation_content_hash(self.model_dump()):
            raise ValueError("content_hash does not match the normalized observation")
        return self


class MacroEvidenceRef(_UwBase):
    obs_id: int
    artifact_id: int
    domain: MacroDomain
    source: str
    source_url: str | None = None
    source_record_id: str
    period_end: date
    published_at: AwareDatetime | None = None
    available_at: AwareDatetime
    first_observed_at: AwareDatetime
    content_hash: str
    parser_version: str
    quality_status: MacroQualityStatus
    cost_class: MacroCostClass

    @field_validator("content_hash")
    @classmethod
    def _sha256_hash(cls, value: str) -> str:
        return _validate_sha256(value)


class PolicyPathProbabilityBucket(_UwBase):
    label: str
    lower_bound_percent: Decimal | None = None
    upper_bound_percent: Decimal | None = None
    probability_percent: Decimal


class PolicyPathParticipantPoint(_UwBase):
    rate_percent: Decimal
    participant_count: int


class PolicyPathPoint(_UwBase):
    horizon: str
    horizon_date: date | None = None
    rate_percent: Decimal
    target_range_lower_percent: Decimal | None = None
    target_range_upper_percent: Decimal | None = None
    action: str | None = None
    #: ``not_stated`` means the publisher printed no vote at all.  The FOMC
    #: parser never produces it -- a statement with no vote paragraph fails
    #: closed and becomes no fact -- so it is reserved for a producer that can
    #: legitimately observe a voteless release.  ``None`` means the path kind
    #: has no vote: an anonymous SEP dot belongs to no named participant.
    vote_status: Literal["stated", "not_stated"] | None = None
    vote_split: str | None = None
    #: Who voted, and whether the publisher said.  A tally alone cannot recover
    #: the composition, and the composition is where the directional signal is.
    #:
    #: The three fields are only meaningful together.  Two of 55 statements in
    #: the 2020+ archive print a tally with no roster, one of them a 9-3 -- so
    #: an empty ``voted_against`` means "no dissenter was NAMED", and equals
    #: "no dissenter" only when ``voter_names_stated`` is true.  Dropping that
    #: flag turns three dissenters into a unanimous committee.
    voted_for: list[str] = Field(default_factory=list)
    voted_against: list[str] = Field(default_factory=list)
    voter_names_stated: bool | None = None
    central_tendency_lower_percent: Decimal | None = None
    central_tendency_upper_percent: Decimal | None = None
    range_lower_percent: Decimal | None = None
    range_upper_percent: Decimal | None = None
    p25_percent: Decimal | None = None
    p75_percent: Decimal | None = None
    respondent_count: int | None = None
    participant_distribution: list[PolicyPathParticipantPoint] = Field(
        default_factory=list
    )
    probability_distribution: list[PolicyPathProbabilityBucket] = Field(
        default_factory=list
    )


class PolicyPath(_UwBase):
    kind: PolicyPathKind
    source: str
    source_kind: MacroSourceKind
    source_record_id: str
    #: The date this release is ABOUT -- the meeting for FOMC and SEP, the response
    #: due date for the dealer survey.  Carried because it is the only date that can
    #: label a release: ``published_at`` is null for publishers that state a date and
    #: not an instant, and ``available_at`` is when WE fetched it, so a backfilled
    #: archive labels every one of its releases with the day of the backfill.
    release_date: date | None = None
    published_at: AwareDatetime | None = None
    available_at: AwareDatetime
    cost_class: MacroCostClass
    delay_status: PolicyPathDelayStatus = "not_applicable"
    delay_minutes: int | None = None
    points: list[PolicyPathPoint]
    evidence_refs: list[MacroEvidenceRef] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_source_contract(self) -> "PolicyPath":
        if self.kind == "market_implied":
            if self.source_kind != "third_party_shadow":
                raise ValueError(
                    "market_implied source_kind must be third_party_shadow"
                )
            if self.cost_class != "free_third_party_shadow":
                raise ValueError(
                    "third_party_shadow evidence requires "
                    "free_third_party_shadow cost_class"
                )
            if self.delay_status == "not_applicable":
                raise ValueError(
                    "third_party_shadow evidence requires explicit delay_status"
                )
            if self.delay_status == "known" and (
                self.delay_minutes is None or self.delay_minutes < 0
            ):
                raise ValueError(
                    "third_party_shadow evidence with known delay requires minutes"
                )
            if self.delay_status == "unknown" and self.delay_minutes is not None:
                raise ValueError(
                    "third_party_shadow evidence cannot attach minutes to unknown delay"
                )
        elif self.source_kind == "third_party_shadow":
            raise ValueError("third_party_shadow evidence must be market_implied")
        elif self.delay_status != "not_applicable" or self.delay_minutes is not None:
            raise ValueError("delay labels only apply to market_implied paths")
        if not self.points:
            raise ValueError("policy path requires at least one point")
        return self


class PolicyReleaseFailure(_UwBase):
    """One named release whose evidence landed but whose facts did not.

    Named rather than counted: an operator cannot re-run "the 3 that failed",
    only a specific release key.
    """

    release_key: str
    event_date: date
    error_type: str | None = None
    error_message: str | None = None


class PolicySourceFreshness(_UwBase):
    source: str
    status: Literal["ok", "degraded", "missing"]
    last_attempt_at: AwareDatetime | None = None
    last_success_at: AwareDatetime | None = None
    consecutive_failures: int = 0
    error_type: str | None = None
    error_message: str | None = None
    #: Release coverage as of the same instant as the path itself.  A source can
    #: be ``ok`` on its latest release and still be missing half its history, so
    #: these counts answer a question ``status`` cannot.
    releases_discovered: int = Field(
        default=0,
        description=(
            "Releases this deployment has attempted by as_of. This is our own "
            "attempt log, NOT the publisher's archive: a source we have never "
            "backfilled reports a small complete-looking window rather than a "
            "hole. Use the backfill's coverage audit to compare against the "
            "published archive."
        ),
    )
    releases_succeeded: int = Field(
        default=0, description="Attempted releases that produced a durable fact."
    )
    releases_failed: int = Field(
        default=0,
        description=(
            "Attempted releases that produced no fact, for any reason — a failed "
            "parse and bytes-without-a-reading both count. Always equals "
            "releases_discovered minus releases_succeeded."
        ),
    )
    release_failures: list[PolicyReleaseFailure] = Field(
        default_factory=list,
        description=(
            "Oldest failures first, capped: the deepest hole is the one a "
            "backfill has to reach. May be shorter than releases_failed."
        ),
    )

    @model_validator(mode="after")
    def _counts_are_consistent(self) -> "PolicySourceFreshness":
        if (
            min(self.releases_discovered, self.releases_succeeded, self.releases_failed)
            < 0
        ):
            raise ValueError("policy release counts cannot be negative")
        if self.releases_succeeded + self.releases_failed != self.releases_discovered:
            raise ValueError(
                "policy release outcomes must account for every release discovered"
            )
        if len(self.release_failures) > self.releases_failed:
            raise ValueError(
                "policy release failure details cannot exceed the failure count"
            )
        return self


class PolicyPathSlot(_UwBase):
    kind: PolicyPathKind
    path: PolicyPath | None = None
    #: Earlier releases from THIS publisher, newest first, so a reader can see how
    #: one publisher's own view moved.  Separate from ``path`` on purpose: each is
    #: its own dated release, never merged into the current one and never averaged
    #: with it.  Empty when only one release has been ingested.
    prior: list[PolicyPath] = Field(default_factory=list)
    missing_reason: str | None = None
    freshness: PolicySourceFreshness

    @model_validator(mode="after")
    def _path_or_reason(self) -> "PolicyPathSlot":
        if (self.path is None) == (self.missing_reason is None):
            raise ValueError(
                "policy path slot requires exactly one path or missing_reason"
            )
        if self.path is not None and self.path.kind != self.kind:
            raise ValueError("policy path slot kind does not match path")
        if any(earlier.kind != self.kind for earlier in self.prior):
            raise ValueError("policy path slot kind does not match a prior release")
        if self.path is None and self.prior:
            raise ValueError("a slot with no current path cannot carry prior releases")
        return self


class PolicyComparison(_UwBase):
    as_of: AwareDatetime
    actual: PolicyPathSlot
    committee_projection: PolicyPathSlot
    dealer_expectations: PolicyPathSlot
    market_implied: PolicyPathSlot
    contradictions: list[str] = Field(default_factory=list)


class MacroVelocityItem(_UwBase):
    """How fast, with its metric, unit and window -- never a bare number."""

    metric: str
    value: Decimal | None = None
    unit: str
    window_months: int
    unavailable_reason: str | None = None


#: How to read a confidence term's value.
#: - ``multiplicand``: in the product; 1 is neutral, below 1 drags.
#: - ``penalty``: in the product as ``(1 - value)``; 0 is neutral, above 0 drags.
#: - ``informational``: NOT in the product; the value is a count or a flag.
ConfidenceTermKind = Literal["multiplicand", "penalty", "informational"]


class MacroConfidenceReason(_UwBase):
    """One term behind a confidence number, so the number can be argued with.

    ``kind`` is what lets a reader know whether a value drags: 1.00 is neutral for a
    multiplicand and total for a penalty, and an informational term is not in the
    product at all.  Without it every consumer re-derives the distinction by matching
    on term names.
    """

    term: str
    value: Decimal
    detail: str
    kind: ConfidenceTermKind = "multiplicand"


class MacroContradiction(_UwBase):
    rule: str
    detail: str


class MacroFactorState(_UwBase):
    """One input's own sub-state, carrying its own freshness rather than inheriting one."""

    name: str
    causal_role: MacroCausalRole
    series_id: str
    period_end: date
    value: Decimal
    unit: str
    direction: MacroDirection
    change_over_window: Decimal | None = None
    available_at: AwareDatetime
    age_days: int
    freshness: Decimal
    quality_status: MacroQualityStatus
    source: str
    source_kind: MacroSourceKind


class MacroSubStateItem(_UwBase):
    """One causal role's own read, with its own confidence.

    Kept beside the domain state rather than merged into it because the two have
    different denominators: the rates policy state is gated by the three policy paths and
    nothing else, while a positioning read is gated by whether CFTC published. A surface
    rendering one confidence above a panel holding both would let either stand in for the
    other -- which is the substitution the rates engine exists to refuse.

    ``state`` is a plain string because the vocabularies are per role and not comparable:
    ELEVATED is about issuance size, STRETCHED_LOW is a percentile of a position. A
    shared enum would invite exactly that comparison. Every vocabulary includes
    ``UNKNOWN`` and none includes ``NEUTRAL`` -- absence is not a centred reading.
    """

    role: MacroCausalRole
    state: str
    direction: MacroDirection
    confidence: Decimal
    series_ids: list[str] = Field(default_factory=list)
    latest_period_end: date | None = None
    unavailable_reason: str | None = None
    velocity: list[MacroVelocityItem] = Field(default_factory=list)
    confidence_reasons: list[MacroConfidenceReason] = Field(default_factory=list)


class MacroStateEvidenceItem(_UwBase):
    """One observation the state stood on, in the order the engine used it."""

    ordinal: int
    obs_id: int
    artifact_id: int
    causal_role: MacroCausalRole
    series_id: str
    period_end: date
    unit: str
    value_numeric: Decimal | None = None
    available_at: AwareDatetime
    source: str
    source_kind: MacroSourceKind
    quality_status: MacroQualityStatus


class MacroDomainStateResponse(_UwBase):
    """A stored answer, replayed -- never recomputed at read time.

    ``requested_as_of`` and ``as_of`` are separate because they routinely differ: the
    reply is the most recent state that answers for a time at or before the request, so
    asking about right now returns the last state actually computed.  Collapsing them
    would present a day-old answer as a live one.
    """

    domain: MacroDomain
    requested_as_of: AwareDatetime
    as_of: AwareDatetime
    computed_at: AwareDatetime
    engine_version: str
    inputs_hash: str
    state: str
    direction: MacroDirection
    confidence: Decimal
    freshness: MacroStateFreshness
    age_hours: float
    velocity: list[MacroVelocityItem] = Field(default_factory=list)
    confidence_reasons: list[MacroConfidenceReason] = Field(default_factory=list)
    contradictions: list[MacroContradiction] = Field(default_factory=list)
    factors: list[MacroFactorState] = Field(default_factory=list)
    evidence: list[MacroStateEvidenceItem] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    sub_states: list[MacroSubStateItem] = Field(default_factory=list)


class MacroStateSummary(_UwBase):
    """The state without its lineage, for surfaces that already carry a large payload.

    ``detail_path`` is not decoration: a block that shows a conclusion and hides what it
    stood on is the shape this milestone exists to replace, so the full evidence is
    always one documented hop away.
    """

    domain: MacroDomain
    as_of: AwareDatetime
    computed_at: AwareDatetime
    engine_version: str
    state: str
    direction: MacroDirection
    confidence: Decimal
    freshness: MacroStateFreshness
    age_hours: float
    velocity: list[MacroVelocityItem] = Field(default_factory=list)
    confidence_reasons: list[MacroConfidenceReason] = Field(default_factory=list)
    contradictions: list[MacroContradiction] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    evidence_count: int = 0
    detail_path: str


def _validate_sha256(value: str) -> str:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError("content_hash must be lowercase SHA-256 hex")
    return value


_preserve_public_module(
    MacroSourceArtifact,
    MacroObservation,
    MacroEvidenceRef,
    PolicyPathProbabilityBucket,
    PolicyPathParticipantPoint,
    PolicyPathPoint,
    PolicyPath,
    PolicyReleaseFailure,
    PolicySourceFreshness,
    PolicyPathSlot,
    PolicyComparison,
    MacroVelocityItem,
    MacroConfidenceReason,
    MacroContradiction,
    MacroFactorState,
    MacroStateEvidenceItem,
    MacroDomainStateResponse,
    MacroStateSummary,
)
