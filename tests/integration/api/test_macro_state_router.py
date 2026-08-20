"""The domain-state endpoints, which replay stored answers rather than recomputing them.

The distinction is the whole point of the endpoint.  A replay that recomputed with
today's engine would report what we *would* have said about March, which is not what we
said in March -- and an audit trail you can regenerate to taste is not an audit trail.
So the contract under test is: return the stored state, name the evidence it stood on,
and 404 rather than invent one for an instant nobody answered.

States are produced by the real jobs over the preregistered disinflation scenario's
sixteen months of eight real ALFRED series, not hand-built rows.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from fastapi.testclient import TestClient

from tests.integration.worker.test_macro_state_jobs import (
    DISINFLATION_AS_OF,
    _golden_scenario,
    _ingest_scenario,
)
from uw_scan.config import Settings
from uw_scan.storage.repository import Repository
from uw_scan.worker.jobs.macro_state_jobs import macro_inflation_state_job


def _settings() -> Settings:
    test_db = os.environ.get("UW_SCAN_TEST_DB_NAME")
    if not test_db:
        pytest.fail("UW_SCAN_TEST_DB_NAME is not set", pytrace=False)
    os.environ.setdefault("UW_SCAN_API_KEY", "test-dummy-not-used")
    return Settings.from_env().model_copy(update={"db_name": test_db})


def _seed_state(as_of: datetime = DISINFLATION_AS_OF) -> int:
    settings = _settings()
    _ingest_scenario(settings, _golden_scenario())
    with psycopg.connect(settings.db_dsn()) as conn:
        result = macro_inflation_state_job(
            Repository(conn, schema="uw_scan"), as_of=as_of
        )
    assert result.status == "ok", result.error_message
    return result.state_id


class TestReplay:
    def test_a_stored_state_is_returned_with_the_evidence_it_stood_on(
        self, client: TestClient, seeded_db_empty_cards
    ) -> None:
        _seed_state()

        response = client.get(
            "/api/macro/inflation",
            params={"as_of_ts": DISINFLATION_AS_OF.isoformat()},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["state"] == "WELL_ABOVE_TARGET"
        assert body["direction"] == "FALLING"
        assert body["domain"] == "inflation"
        assert body["engine_version"] == "inflation/1"
        assert len(body["evidence"]) == 8 * 16
        assert len(body["factors"]) == 8
        first = body["evidence"][0]
        assert first["obs_id"] > 0
        assert first["source_kind"] == "first_party_publisher"

    def test_no_evidence_may_postdate_the_instant_the_state_answers_for(
        self, client: TestClient, seeded_db_empty_cards
    ) -> None:
        _seed_state()

        body = client.get(
            "/api/macro/inflation",
            params={"as_of_ts": DISINFLATION_AS_OF.isoformat()},
        ).json()

        as_of = datetime.fromisoformat(body["as_of"])
        assert all(
            datetime.fromisoformat(item["available_at"]) <= as_of
            for item in body["evidence"]
        )

    def test_replaying_before_any_state_existed_is_a_404_not_an_invented_state(
        self, client: TestClient, seeded_db_empty_cards
    ) -> None:
        _seed_state()

        response = client.get("/api/macro/inflation", params={"as_of": "2020-01-01"})

        assert response.status_code == 404
        assert "no inflation state has been computed" in response.json()["detail"]

    def test_a_later_request_returns_the_state_in_force_not_a_newer_one(
        self, client: TestClient, seeded_db_empty_cards
    ) -> None:
        """Two answers exist; a replay must pick the one that answered for that time."""
        settings = _settings()
        _ingest_scenario(settings, _golden_scenario())
        later_as_of = DISINFLATION_AS_OF + timedelta(days=2)
        with psycopg.connect(settings.db_dsn()) as conn:
            repo = Repository(conn, schema="uw_scan")
            first = macro_inflation_state_job(repo, as_of=DISINFLATION_AS_OF)
            second = macro_inflation_state_job(repo, as_of=later_as_of)
        assert first.state_id != second.state_id

        body = client.get(
            "/api/macro/inflation",
            params={"as_of_ts": (DISINFLATION_AS_OF + timedelta(hours=1)).isoformat()},
        ).json()

        assert datetime.fromisoformat(body["as_of"]) == DISINFLATION_AS_OF

    def test_an_uncomputed_domain_is_a_404_rather_than_an_empty_state(
        self, client: TestClient, seeded_db_empty_cards
    ) -> None:
        _seed_state()
        assert client.get("/api/macro/rates").status_code == 404


class TestStaleness:
    def test_a_state_answering_for_its_own_instant_is_fresh(
        self, client: TestClient, seeded_db_empty_cards
    ) -> None:
        _seed_state()

        body = client.get(
            "/api/macro/inflation",
            params={"as_of_ts": DISINFLATION_AS_OF.isoformat()},
        ).json()

        assert body["freshness"] == "fresh"
        assert body["age_hours"] == 0.0

    def test_a_state_nobody_has_recomputed_is_labelled_stale(
        self, client: TestClient, seeded_db_empty_cards
    ) -> None:
        _seed_state()

        body = client.get(
            "/api/macro/inflation",
            params={"as_of_ts": (DISINFLATION_AS_OF + timedelta(days=4)).isoformat()},
        ).json()

        # Still the honest answer to the question asked -- just plainly labelled as one
        # nothing has revisited, rather than dressed up as current.
        assert body["freshness"] == "stale"
        assert body["age_hours"] == pytest.approx(96.0)
        assert body["state"] == "WELL_ABOVE_TARGET"

    def test_requested_and_answered_instants_are_reported_separately(
        self, client: TestClient, seeded_db_empty_cards
    ) -> None:
        _seed_state()
        requested = DISINFLATION_AS_OF + timedelta(days=1)

        body = client.get(
            "/api/macro/inflation", params={"as_of_ts": requested.isoformat()}
        ).json()

        assert datetime.fromisoformat(body["requested_as_of"]) == requested
        assert datetime.fromisoformat(body["as_of"]) == DISINFLATION_AS_OF


class TestInstantArguments:
    def test_two_instants_are_refused_rather_than_one_silently_winning(
        self, client: TestClient, seeded_db_empty_cards
    ) -> None:
        response = client.get(
            "/api/macro/inflation",
            params={"as_of": "2023-07-28", "as_of_ts": DISINFLATION_AS_OF.isoformat()},
        )
        assert response.status_code == 422

    def test_a_naive_instant_is_refused_because_it_is_a_timezone_guess(
        self, client: TestClient, seeded_db_empty_cards
    ) -> None:
        response = client.get(
            "/api/macro/inflation", params={"as_of_ts": "2023-07-28T12:00:00"}
        )
        assert response.status_code == 422
        assert "UTC offset" in response.json()["detail"]

    def test_a_calendar_date_replays_to_the_end_of_that_day(
        self, client: TestClient, seeded_db_empty_cards
    ) -> None:
        _seed_state()

        body = client.get("/api/macro/inflation", params={"as_of": "2023-07-28"}).json()

        requested = datetime.fromisoformat(body["requested_as_of"])
        assert requested.tzinfo is not None
        assert requested.astimezone(UTC).date().isoformat() == "2023-07-28"
        assert requested.astimezone(UTC).hour == 23
