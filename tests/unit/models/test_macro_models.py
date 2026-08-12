from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from uw_scan.macro_evidence import (
    macro_artifact_content_identity,
    macro_observation_content_hash,
)
from uw_scan.models import MacroEvidenceRef, MacroObservation, MacroSourceArtifact

RAW_ARTIFACT = {"value": "319.1"}
HASH_A, CONTENT_LENGTH = macro_artifact_content_identity(raw_json=RAW_ARTIFACT)


def _artifact_payload() -> dict[str, object]:
    return {
        "artifact_id": 7,
        "source": "BLS",
        "source_kind": "official",
        "source_record_id": "cpi-2026-02-12",
        "source_url": "https://example.test/release",
        "published_at": datetime(2026, 2, 12, 13, 30, tzinfo=UTC),
        "available_at": datetime(2026, 2, 12, 13, 30, tzinfo=UTC),
        "retrieved_at": datetime(2026, 2, 12, 13, 31, tzinfo=UTC),
        "last_seen_at": datetime(2026, 2, 12, 13, 31, tzinfo=UTC),
        "content_hash": HASH_A,
        "parser_version": "bls-cpi-v1",
        "quality_status": "valid",
        "cost_class": "free_official",
        "media_type": "application/json",
        "content_length": CONTENT_LENGTH,
        "raw_json": RAW_ARTIFACT,
    }


def test_macro_source_artifact_requires_timezone_aware_instants() -> None:
    payload = _artifact_payload()
    payload["retrieved_at"] = datetime(2026, 2, 12, 13, 31)

    with pytest.raises(ValidationError):
        MacroSourceArtifact.model_validate(payload)


def test_macro_source_artifact_requires_exactly_one_raw_payload() -> None:
    payload = _artifact_payload()
    payload["raw_text"] = "duplicate representation"

    with pytest.raises(ValidationError):
        MacroSourceArtifact.model_validate(payload)


def test_macro_source_artifact_rejects_unknown_cost_class() -> None:
    payload = _artifact_payload()
    payload["cost_class"] = "free_maybe"

    with pytest.raises(ValidationError):
        MacroSourceArtifact.model_validate(payload)


def test_canonical_artifact_identity_normalizes_json_order_and_numbers() -> None:
    first = macro_artifact_content_identity(raw_json={"b": 1.0, "a": "黄金"})
    second = macro_artifact_content_identity(raw_json={"a": "黄金", "b": 1})

    assert first == second


def test_macro_observation_preserves_decimal_and_unit() -> None:
    payload = {
        "obs_id": 11,
        "artifact_id": 7,
        "domain": "inflation",
        "series_id": "CPI_ALL_ITEMS",
        "period_end": date(2026, 1, 31),
        "frequency": "monthly",
        "unit": "index_1982_1984_100",
        "value_numeric": Decimal("319.1000"),
        "source": "BLS",
        "source_record_id": "cpi-2026-02-12",
        "published_at": datetime(2026, 2, 12, 13, 30, tzinfo=UTC),
        "available_at": datetime(2026, 2, 12, 13, 30, tzinfo=UTC),
        "first_observed_at": datetime(2026, 2, 12, 13, 31, tzinfo=UTC),
        "last_seen_at": datetime(2026, 2, 12, 13, 31, tzinfo=UTC),
        "parser_version": "bls-cpi-v1",
        "quality_status": "valid",
        "cost_class": "free_official",
    }
    payload["content_hash"] = macro_observation_content_hash(payload)
    observation = MacroObservation.model_validate(payload)

    assert observation.value_numeric == Decimal("319.1000")
    assert observation.unit == "index_1982_1984_100"
    assert observation.__class__.__module__ == "uw_scan.models"

    equivalent = {**payload, "value_numeric": Decimal("319.1")}
    assert macro_observation_content_hash(equivalent) == payload["content_hash"]


def test_macro_observation_requires_exactly_one_value() -> None:
    with pytest.raises(ValidationError):
        MacroObservation.model_validate(
            {
                "artifact_id": 7,
                "domain": "inflation",
                "series_id": "CPI_ALL_ITEMS",
                "period_end": date(2026, 1, 31),
                "frequency": "monthly",
                "unit": "index_1982_1984_100",
                "value_numeric": Decimal("319.1"),
                "value_text": "319.1",
                "source": "BLS",
                "source_record_id": "cpi-2026-02-12",
                "available_at": datetime(2026, 2, 12, 13, 30, tzinfo=UTC),
                "first_observed_at": datetime(2026, 2, 12, 13, 31, tzinfo=UTC),
                "last_seen_at": datetime(2026, 2, 12, 13, 31, tzinfo=UTC),
                "content_hash": HASH_A,
                "parser_version": "bls-cpi-v1",
                "quality_status": "valid",
                "cost_class": "free_official",
            }
        )


def test_macro_evidence_ref_round_trips_ids_and_times() -> None:
    evidence = MacroEvidenceRef(
        obs_id=11,
        artifact_id=7,
        domain="inflation",
        source="BLS",
        source_url="https://example.test/release",
        source_record_id="cpi-2026-02-12",
        period_end=date(2026, 1, 31),
        published_at=datetime(2026, 2, 12, 13, 30, tzinfo=UTC),
        available_at=datetime(2026, 2, 12, 13, 30, tzinfo=UTC),
        first_observed_at=datetime(2026, 2, 12, 13, 31, tzinfo=UTC),
        content_hash=HASH_A,
        parser_version="bls-cpi-v1",
        quality_status="valid",
        cost_class="free_official",
    )

    restored = MacroEvidenceRef.model_validate_json(evidence.model_dump_json())

    assert restored.obs_id == 11
    assert restored.artifact_id == 7
    assert restored.available_at == evidence.available_at


def test_macro_models_reject_non_sha256_hash_and_reversed_times() -> None:
    payload = _artifact_payload()
    payload["content_hash"] = "placeholder"
    with pytest.raises(ValidationError):
        MacroSourceArtifact.model_validate(payload)

    payload = _artifact_payload()
    payload["published_at"] = datetime(2026, 2, 12, 13, 32, tzinfo=UTC)
    payload["available_at"] = datetime(2026, 2, 12, 13, 31, tzinfo=UTC)
    with pytest.raises(
        ValidationError, match="published_at must not follow available_at"
    ):
        MacroSourceArtifact.model_validate(payload)
