"""The generic ingest and its reads, over HTTP.

The tenant-neutrality test at the bottom is the point of the whole design: a
tenant argon has never heard of ingests and reads back identically, with no
code change anywhere below the view layer.
"""

from __future__ import annotations

import os

import psycopg
import pytest
from fastapi.testclient import TestClient

from uw_scan.api.deps import get_repo, get_settings
from uw_scan.api.server import create_app
from uw_scan.config import Settings
from uw_scan.storage.repository import Repository

TOKEN = "test-ingest-token-not-a-real-secret"

# Frozen from the recorded option-wizard run of 2026-09-03.
VIEW = {
    "date": "2026-09-03",
    "tape": [
        {"label": "SPY", "value": "772.80"},
        {"label": "QQQ", "value": "717.47"},
        {"label": "10Y", "value": "4.79%", "source": "DGS10, 2026-09-01"},
    ],
}
VIEW_LATER = {
    "date": "2026-09-04",
    "tape": [
        {"label": "NVDA", "value": "227.60"},
        {"label": "AVGO", "value": "355.90"},
    ],
}


def _settings(token: str | None) -> Settings:
    test_db = os.environ.get("UW_SCAN_TEST_DB_NAME")
    if not test_db:
        pytest.fail("UW_SCAN_TEST_DB_NAME not set", pytrace=False)
    os.environ.setdefault("UW_SCAN_API_KEY", "test-dummy-not-used-by-db-tests")
    from pydantic import SecretStr

    return Settings.from_env().model_copy(
        update={
            "db_name": test_db,
            "agent_ingest_token": SecretStr(token) if token else None,
        }
    )


def _client(settings: Settings) -> TestClient:
    app = create_app()

    def _override_repo():
        conn = psycopg.connect(settings.db_dsn())
        try:
            yield Repository(conn, schema=settings.db_schema)
        finally:
            conn.close()

    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_repo] = _override_repo
    return TestClient(app)


@pytest.fixture
def ingest_client(seeded_db_empty_cards) -> TestClient:
    """A client whose ingest token IS configured."""
    client = _client(_settings(TOKEN))
    try:
        yield client
    finally:
        client.app.dependency_overrides.clear()


@pytest.fixture
def tokenless_client(seeded_db_empty_cards) -> TestClient:
    """A client built with the env var absent — ingest must be disabled."""
    client = _client(_settings(None))
    try:
        yield client
    finally:
        client.app.dependency_overrides.clear()


def _payload(**over):
    base = dict(
        tenant="option-wizard",
        kind="premarket",
        run_day="2026-09-03",
        week_key="2026-W36",
        run_id="ow-2026-09-03-premarket-1",
        code_sha="a1b2c3d",
        schema_version=1,
        outcome="completed",
        headline="SPY 772.80, one sentence.",
        view=VIEW,
    )
    base.update(over)
    return base


def _post(client: TestClient, token: str | None = TOKEN, **over):
    headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
    return client.post("/api/agent-runs", json=_payload(**over), headers=headers)


def test_a_missing_token_and_a_wrong_token_take_the_same_path(ingest_client):
    assert _post(ingest_client, token=None).status_code == 401
    assert _post(ingest_client, token="not-the-token").status_code == 401


def test_ingest_is_disabled_rather_than_open_when_no_token_is_configured(
    tokenless_client,
):
    response = _post(tokenless_client)
    assert response.status_code == 503
    assert "UW_SCAN_AGENT_INGEST_TOKEN" in response.json()["detail"]


def test_a_valid_post_creates_the_run(ingest_client):
    response = _post(ingest_client)
    assert response.status_code == 201
    assert response.json() == {
        "tenant": "option-wizard",
        "kind": "premarket",
        "run_day": "2026-09-03",
        "week_key": "2026-W36",
        "version_no": 1,
        "created": True,
    }


def test_reposting_the_same_run_id_is_not_a_second_run(ingest_client):
    assert _post(ingest_client).status_code == 201
    repeat = _post(ingest_client)
    assert repeat.status_code == 200
    assert repeat.json()["created"] is False
    assert repeat.json()["version_no"] == 1


def test_a_kind_that_is_not_a_slug_is_refused_at_the_boundary(ingest_client):
    assert _post(ingest_client, kind="PREMARKET").status_code == 422


def test_the_week_index_lists_every_recorded_kind_and_carries_no_documents(
    ingest_client,
):
    _post(ingest_client)
    _post(
        ingest_client,
        kind="close",
        run_id="ow-2026-09-03-close-1",
        view=VIEW_LATER,
    )
    body = ingest_client.get(
        "/api/agent-runs/week/2026-W36", params={"tenant": "option-wizard"}
    ).json()
    assert body["tenant"] == "option-wizard"
    assert sorted(r["kind"] for r in body["runs"]) == ["close", "premarket"]
    assert all("view" not in r for r in body["runs"])


def test_weeks_are_newest_first_and_only_recorded_ones_appear(ingest_client):
    _post(ingest_client)
    _post(
        ingest_client,
        run_day="2026-09-08",
        week_key="2026-W37",
        run_id="ow-2026-09-08-premarket-1",
        view=VIEW_LATER,
    )
    body = ingest_client.get(
        "/api/agent-runs/weeks", params={"tenant": "option-wizard"}
    ).json()
    assert [w["week_key"] for w in body["weeks"]] == ["2026-W37", "2026-W36"]
    assert body["weeks"][1]["run_count"] == 1


def test_one_run_reads_back_its_document_and_the_build_that_wrote_it(ingest_client):
    _post(ingest_client)
    body = ingest_client.get(
        "/api/agent-runs/run/premarket/2026-09-03",
        params={"tenant": "option-wizard"},
    ).json()
    assert body["view"] == VIEW
    assert body["code_sha"] == "a1b2c3d"
    assert body["week_key"] == "2026-W36"


def test_a_missing_run_names_the_kind_tenant_and_date(ingest_client):
    response = ingest_client.get(
        "/api/agent-runs/run/premarket/2026-09-02",
        params={"tenant": "option-wizard"},
    )
    assert response.status_code == 404
    detail = response.json()["detail"]
    assert "2026-09-02" in detail
    assert "option-wizard" in detail
    assert "premarket" in detail


def test_latest_is_the_newest_recorded_day(ingest_client):
    _post(ingest_client)
    _post(
        ingest_client,
        kind="close",
        run_day="2026-09-04",
        run_id="ow-2026-09-04-close-1",
        view=VIEW_LATER,
    )
    body = ingest_client.get(
        "/api/agent-runs/latest", params={"tenant": "option-wizard"}
    ).json()
    assert body["run_day"] == "2026-09-04"
    assert body["kind"] == "close"


def test_a_tenant_argon_has_never_heard_of_round_trips_identically(ingest_client):
    """The whole point of the design: a new tenant is a POST, not a release."""
    created = _post(
        ingest_client,
        tenant="livewire-shepherd",
        kind="heal",
        run_id="ls-2026-09-03-heal-1",
        week_key="2026-W36",
        headline="3 gaps healed.",
        view={"date": "2026-09-03", "healed": 3},
    )
    assert created.status_code == 201
    assert created.json()["tenant"] == "livewire-shepherd"

    index = ingest_client.get(
        "/api/agent-runs/week/2026-W36", params={"tenant": "livewire-shepherd"}
    ).json()
    assert [r["kind"] for r in index["runs"]] == ["heal"]

    run = ingest_client.get(
        "/api/agent-runs/run/heal/2026-09-03",
        params={"tenant": "livewire-shepherd"},
    ).json()
    assert run["view"] == {"date": "2026-09-03", "healed": 3}

    # And it is invisible to the other tenant.
    other = ingest_client.get(
        "/api/agent-runs/weeks", params={"tenant": "option-wizard"}
    ).json()
    assert other["weeks"] == []
