from __future__ import annotations

from datetime import UTC, date, datetime

from fastapi.testclient import TestClient

from uw_scan.macro_evidence import (
    macro_artifact_content_identity,
    macro_observation_content_hash,
)
from uw_scan.storage.repository import Repository


RELEASED_AT = datetime(2026, 6, 17, 18, tzinfo=UTC)


def _insert_path(
    repo: Repository,
    *,
    kind: str,
    series_id: str,
    source: str,
    source_kind: str = "official",
    cost_class: str = "free_official",
    delay_minutes: int | None = None,
    delay_status: str = "not_applicable",
) -> None:
    record_id = f"{source}:2026-06:primary"
    raw_json = {"source": source, "release": "2026-06"}
    content_hash, content_length = macro_artifact_content_identity(raw_json=raw_json)
    artifact_id = repo.insert_macro_artifact(
        source=source,
        source_kind=source_kind,
        source_record_id=record_id,
        source_url=f"https://official.example/{source}/2026-06",
        published_at=RELEASED_AT,
        available_at=RELEASED_AT,
        retrieved_at=RELEASED_AT,
        content_hash=content_hash,
        parser_version="test.policy.v1",
        quality_status="partial",
        cost_class=cost_class,
        media_type="application/json",
        content_length=content_length,
        raw_json=raw_json,
    )
    value = {
        "kind": kind,
        "delay_status": delay_status,
        "delay_minutes": delay_minutes,
        "points": [
            {
                "horizon": "2026",
                "horizon_date": "2026-12-31",
                "rate_percent": "3.8",
            }
        ],
    }
    row = {
        "artifact_id": artifact_id,
        "domain": "policy_rates",
        "series_id": series_id,
        "period_end": date(2026, 6, 17),
        "frequency": "event",
        "unit": "policy_path_json",
        "value_json": value,
        "source": source,
        "source_record_id": record_id,
        "published_at": RELEASED_AT,
        "available_at": RELEASED_AT,
        "parser_version": "test.policy.v1",
        "quality_status": "partial",
        "cost_class": cost_class,
    }
    row["content_hash"] = macro_observation_content_hash(row)
    repo.insert_macro_observations([row], seen_at=RELEASED_AT)
    repo.upsert_macro_source_status(source, status="ok", attempted_at=RELEASED_AT)
    repo.conn.commit()


def test_policy_api_historical_as_of_hides_future_release_and_exposes_evidence(
    seeded_db_empty_cards: Repository,
    client: TestClient,
) -> None:
    _insert_path(
        seeded_db_empty_cards,
        kind="committee_projection",
        series_id="POLICY_PATH_COMMITTEE_PROJECTION",
        source="federal_reserve_sep",
    )

    before = client.get("/api/macro/policy", params={"as_of": "2026-06-16"})
    after = client.get("/api/macro/policy", params={"as_of": "2026-06-17"})

    assert before.status_code == 200
    assert before.json()["committee_projection"]["path"] is None
    assert "no PIT-eligible" in before.json()["committee_projection"]["missing_reason"]
    assert after.status_code == 200
    path = after.json()["committee_projection"]["path"]
    assert path["kind"] == "committee_projection"
    assert path["points"][0]["rate_percent"] == "3.8"
    assert path["evidence_refs"][0]["source"] == "federal_reserve_sep"
    assert path["evidence_refs"][0]["source_url"].startswith("https://")
    assert after.json()["committee_projection"]["freshness"]["status"] == "ok"


def test_policy_api_keeps_valid_path_when_its_latest_ingest_is_degraded(
    seeded_db_empty_cards: Repository,
    client: TestClient,
) -> None:
    _insert_path(
        seeded_db_empty_cards,
        kind="dealer_expectations",
        series_id="POLICY_PATH_DEALER_EXPECTATIONS",
        source="new_york_fed_sme",
    )
    seeded_db_empty_cards.upsert_macro_source_status(
        "new_york_fed_sme",
        status="degraded",
        attempted_at=datetime(2026, 6, 18, 12, tzinfo=UTC),
        error_type="uw_scan.normalize.NormalizationError",
        error_message="publisher labels changed",
    )
    seeded_db_empty_cards.conn.commit()

    response = client.get("/api/macro/policy", params={"as_of": "2026-06-18"})

    assert response.status_code == 200
    slot = response.json()["dealer_expectations"]
    assert slot["path"] is not None
    assert slot["freshness"]["status"] == "degraded"
    assert slot["freshness"]["consecutive_failures"] == 1
    assert slot["freshness"]["error_type"].endswith("NormalizationError")


def test_market_shadow_never_substitutes_for_missing_official_paths(
    seeded_db_empty_cards: Repository,
    client: TestClient,
) -> None:
    _insert_path(
        seeded_db_empty_cards,
        kind="market_implied",
        series_id="POLICY_PATH_MARKET_IMPLIED",
        source="frenzy_capital",
        source_kind="third_party_shadow",
        cost_class="free_third_party_shadow",
        delay_minutes=15,
        delay_status="known",
    )

    response = client.get("/api/macro/policy", params={"as_of": "2026-06-18"})

    assert response.status_code == 200
    body = response.json()
    assert body["market_implied"]["path"]["source"] == "frenzy_capital"
    assert body["market_implied"]["path"]["source_kind"] == "third_party_shadow"
    assert body["market_implied"]["path"]["delay_minutes"] == 15
    assert body["market_implied"]["path"]["delay_status"] == "known"
    assert body["actual"]["path"] is None
    assert body["committee_projection"]["path"] is None
    assert body["dealer_expectations"]["path"] is None


def test_macro_policy_openapi_preserves_named_contracts(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()

    response = schema["paths"]["/api/macro/policy"]["get"]["responses"]["200"]
    assert response["content"]["application/json"]["schema"]["$ref"].endswith(
        "/PolicyComparison"
    )
    for component in (
        "PolicyComparison",
        "PolicyPathSlot",
        "PolicyPath",
        "PolicyPathPoint",
        "PolicySourceFreshness",
        "MacroEvidenceRef",
    ):
        assert component in schema["components"]["schemas"]
