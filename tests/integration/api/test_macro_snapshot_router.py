"""The context-snapshot endpoint: one object that owns the four-domain composition.

Until this route existed the page composed four independent latest reads, so a chain in
which one domain never ran rendered as four fresh cards. The contract here is that the
snapshot is served with its refusal intact -- the status and the per-domain reason -- and
that an instant nobody assembled one for is a 404 rather than an empty snapshot invented
at read time.

The states come from the real jobs over the preregistered disinflation scenario's sixteen
months of eight real ALFRED series, not hand-built rows.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta

import psycopg
import pytest
from fastapi.testclient import TestClient

from tests.integration.worker.test_macro_state_jobs import (
    DISINFLATION_AS_OF,
    _golden_scenario,
    _ingest_scenario,
)
from uw_scan.config import Settings
from uw_scan.macro.snapshot_assembly import ASSEMBLER_VERSION
from uw_scan.storage.repository import Repository
from uw_scan.worker.jobs.macro_context_snapshot import macro_context_snapshot_job
from uw_scan.worker.jobs.macro_state_jobs import macro_inflation_state_job


def _settings() -> Settings:
    test_db = os.environ.get("UW_SCAN_TEST_DB_NAME")
    if not test_db:
        pytest.fail("UW_SCAN_TEST_DB_NAME is not set", pytrace=False)
    os.environ.setdefault("UW_SCAN_API_KEY", "test-dummy-not-used")
    return Settings.from_env().model_copy(update={"db_name": test_db})


def _seed_inflation_only_snapshot() -> None:
    """One domain answers; the other three never ran. The snapshot must say so."""
    settings = _settings()
    _ingest_scenario(settings, _golden_scenario())
    with psycopg.connect(settings.db_dsn()) as conn:
        repo = Repository(conn, schema="uw_scan")
        result = macro_inflation_state_job(repo, as_of=DISINFLATION_AS_OF)
        assert result.status == "ok", result.error_message
        snapshot = macro_context_snapshot_job(
            repo,
            as_of=DISINFLATION_AS_OF,
            assembled_at=DISINFLATION_AS_OF + timedelta(hours=3),
        )
        assert snapshot is not None
        conn.commit()


class TestTheSnapshotIsServedWithItsRefusal:
    def test_a_partial_chain_reports_partial_and_names_every_gap(
        self, client: TestClient, seeded_db_empty_cards
    ) -> None:
        _seed_inflation_only_snapshot()

        response = client.get(
            "/api/macro/snapshot",
            params={"as_of_ts": DISINFLATION_AS_OF.isoformat()},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "partial"
        assert body["assembler_version"] == ASSEMBLER_VERSION
        assert [d["domain"] for d in body["domains"]] == ["inflation"]
        assert {r["domain"] for r in body["reasons"]} == {
            "policy_rates",
            "usd",
            "gold",
        }
        assert {r["kind"] for r in body["reasons"]} == {"absent"}

    def test_the_domain_row_carries_what_that_domain_said(
        self, client: TestClient, seeded_db_empty_cards
    ) -> None:
        _seed_inflation_only_snapshot()

        body = client.get(
            "/api/macro/snapshot",
            params={"as_of_ts": DISINFLATION_AS_OF.isoformat()},
        ).json()

        inflation = body["domains"][0]
        assert inflation["ordinal"] == 0
        assert inflation["state"]
        assert inflation["direction"]
        assert inflation["state_id"] > 0

    def test_requested_and_answered_instants_stay_separate(
        self, client: TestClient, seeded_db_empty_cards
    ) -> None:
        _seed_inflation_only_snapshot()
        later = DISINFLATION_AS_OF + timedelta(days=2)

        body = client.get(
            "/api/macro/snapshot", params={"as_of_ts": later.isoformat()}
        ).json()

        assert datetime.fromisoformat(body["requested_as_of"]) == later
        assert datetime.fromisoformat(body["as_of"]) == DISINFLATION_AS_OF


class TestAnUnassembledInstantIsARefusal:
    def test_before_any_snapshot_exists_the_route_404s(
        self, client: TestClient, seeded_db_empty_cards
    ) -> None:
        response = client.get("/api/macro/snapshot")

        assert response.status_code == 404
        assert "snapshot" in response.json()["detail"]

    def test_an_instant_predating_the_first_snapshot_404s(
        self, client: TestClient, seeded_db_empty_cards
    ) -> None:
        _seed_inflation_only_snapshot()
        before = DISINFLATION_AS_OF - timedelta(days=1)

        response = client.get(
            "/api/macro/snapshot", params={"as_of_ts": before.isoformat()}
        )

        assert response.status_code == 404
