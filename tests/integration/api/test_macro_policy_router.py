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
    point_extra: dict[str, object] | None = None,
) -> int:
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
                **(point_extra or {}),
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
    return artifact_id


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


def _record_release(
    repo: Repository,
    *,
    source: str,
    release_key: str,
    status: str,
    event_date: date,
    attempted_at: datetime,
    release_type: str = "statement",
    event_class: str | None = "scheduled_meeting",
    error_type: str | None = None,
    error_message: str | None = None,
    success_artifact_id: int | None = None,
) -> None:
    repo.upsert_macro_release_status(
        source=source,
        release_key=release_key,
        release_type=release_type,
        status=status,
        event_date=event_date,
        event_class=event_class,
        discovery_url=f"https://official.example/{release_key}",
        parser_version="test.policy.v1",
        last_attempt_at=attempted_at,
        artifact_source_record_id=(
            f"{source}:2026-06:primary" if success_artifact_id is not None else None
        ),
        latest_artifact_id=success_artifact_id,
        success_artifact_id=success_artifact_id,
        error_type=error_type,
        error_message=error_message,
    )
    repo.conn.commit()


def test_a_failed_older_release_is_counted_without_hiding_the_valid_path(
    seeded_db_empty_cards: Repository,
    client: TestClient,
) -> None:
    """Coverage is reported beside the path, never instead of it.

    A 2020 statement we cannot parse does not make the 2026 decision unknown.
    The caller needs both facts to act: the current path is usable, and the
    history behind it has a named hole.
    """
    artifact_id = _insert_path(
        seeded_db_empty_cards,
        kind="actual",
        series_id="POLICY_PATH_ACTUAL",
        source="federal_reserve_fomc",
    )
    _record_release(
        seeded_db_empty_cards,
        source="federal_reserve_fomc",
        release_key="fomc-statement:monetary20260617a",
        status="ok",
        success_artifact_id=artifact_id,
        event_date=date(2026, 6, 17),
        attempted_at=RELEASED_AT,
    )
    _record_release(
        seeded_db_empty_cards,
        source="federal_reserve_fomc",
        release_key="fomc-statement:monetary20200315a",
        status="failed",
        event_date=date(2020, 3, 15),
        event_class="unscheduled_meeting",
        attempted_at=RELEASED_AT,
        error_type="uw_scan.normalize.NormalizationError",
        error_message="unreadable target range",
    )

    response = client.get("/api/macro/policy", params={"as_of": "2026-06-18"})

    assert response.status_code == 200
    slot = response.json()["actual"]
    assert slot["path"] is not None
    freshness = slot["freshness"]
    assert freshness["releases_discovered"] == 2
    assert freshness["releases_succeeded"] == 1
    assert freshness["releases_failed"] == 1
    failures = freshness["release_failures"]
    assert len(failures) == 1
    assert failures[0]["release_key"] == "fomc-statement:monetary20200315a"
    assert failures[0]["event_date"] == "2020-03-15"
    assert failures[0]["error_type"].endswith("NormalizationError")


def test_historical_replay_does_not_leak_a_later_ingest_attempt(
    seeded_db_empty_cards: Repository,
    client: TestClient,
) -> None:
    """Coverage counts are current operational state, not immutable history.

    Asking what was known in June must not reveal that we tried, and failed, to
    read a release in August.  The counts belong to the attempt clock, so an
    attempt after ``as_of`` is simply not visible yet.
    """
    _insert_path(
        seeded_db_empty_cards,
        kind="actual",
        series_id="POLICY_PATH_ACTUAL",
        source="federal_reserve_fomc",
    )
    _record_release(
        seeded_db_empty_cards,
        source="federal_reserve_fomc",
        release_key="fomc-statement:monetary20260729a",
        status="failed",
        event_date=date(2026, 7, 29),
        attempted_at=datetime(2026, 8, 1, 12, tzinfo=UTC),
        error_type="uw_scan.normalize.NormalizationError",
        error_message="later attempt",
    )

    response = client.get("/api/macro/policy", params={"as_of": "2026-06-18"})

    freshness = response.json()["actual"]["freshness"]
    assert freshness["releases_discovered"] == 0
    assert freshness["releases_failed"] == 0
    assert freshness["release_failures"] == []


def test_policy_replay_accepts_an_exact_instant(
    seeded_db_empty_cards: Repository,
    client: TestClient,
) -> None:
    """Date-level replay cannot express the minute a release became public.

    The FOMC publishes at 14:00 ET.  ``as_of=<that date>`` resolves to end of
    day, so it can never prove a strategy reading at 13:59 saw nothing.
    """
    _insert_path(
        seeded_db_empty_cards,
        kind="actual",
        series_id="POLICY_PATH_ACTUAL",
        source="federal_reserve_fomc",
    )

    before = client.get(
        "/api/macro/policy", params={"as_of_ts": "2026-06-17T17:59:59Z"}
    )
    at = client.get("/api/macro/policy", params={"as_of_ts": "2026-06-17T18:00:00Z"})

    assert before.status_code == 200
    assert before.json()["actual"]["path"] is None
    assert at.status_code == 200
    assert at.json()["actual"]["path"] is not None


def test_policy_replay_rejects_two_conflicting_clocks(client: TestClient) -> None:
    response = client.get(
        "/api/macro/policy",
        params={"as_of": "2026-06-17", "as_of_ts": "2026-06-17T18:00:00Z"},
    )

    assert response.status_code == 422


def test_policy_replay_requires_an_unambiguous_instant(client: TestClient) -> None:
    """A naive timestamp is a timezone guess, and the guess is worth an hour."""
    response = client.get(
        "/api/macro/policy", params={"as_of_ts": "2026-06-17T18:00:00"}
    )

    assert response.status_code == 422


def test_actual_path_exposes_whether_the_vote_was_published(
    seeded_db_empty_cards: Repository,
    client: TestClient,
) -> None:
    """A missing vote and an unpublished vote are different facts.

    The parser already records which one it saw; dropping it at the API turns
    "the statement did not print a vote" into "there was no vote".
    """
    _insert_path(
        seeded_db_empty_cards,
        kind="actual",
        series_id="POLICY_PATH_ACTUAL",
        source="federal_reserve_fomc",
        point_extra={"vote_status": "not_stated", "vote_split": None},
    )

    response = client.get("/api/macro/policy", params={"as_of": "2026-06-18"})

    point = response.json()["actual"]["path"]["points"][0]
    assert point["vote_status"] == "not_stated"
    assert point["vote_split"] is None
