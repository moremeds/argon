"""Shared point-in-time macro evidence contracts."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import AwareDatetime, field_validator, model_validator

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


def _validate_sha256(value: str) -> str:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError("content_hash must be lowercase SHA-256 hex")
    return value


_preserve_public_module(
    MacroSourceArtifact,
    MacroObservation,
    MacroEvidenceRef,
)
