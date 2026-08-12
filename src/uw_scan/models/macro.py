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

from ._base import _UwBase, _preserve_public_module


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
    vote_split: str | None = None
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


class PolicySourceFreshness(_UwBase):
    source: str
    status: Literal["ok", "degraded", "missing"]
    last_attempt_at: AwareDatetime | None = None
    last_success_at: AwareDatetime | None = None
    consecutive_failures: int = 0
    error_type: str | None = None
    error_message: str | None = None


class PolicyPathSlot(_UwBase):
    kind: PolicyPathKind
    path: PolicyPath | None = None
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
        return self


class PolicyComparison(_UwBase):
    as_of: AwareDatetime
    actual: PolicyPathSlot
    committee_projection: PolicyPathSlot
    dealer_expectations: PolicyPathSlot
    market_implied: PolicyPathSlot
    contradictions: list[str] = Field(default_factory=list)


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
    PolicySourceFreshness,
    PolicyPathSlot,
    PolicyComparison,
)
