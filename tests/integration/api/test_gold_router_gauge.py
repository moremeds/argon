"""Gold router — /api/gold/gauge + /api/gold/inputs."""

from __future__ import annotations

import os
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import psycopg
import pytest
from fastapi.testclient import TestClient

from uw_scan.api.deps import get_repo, get_settings
from uw_scan.api.server import create_app
from uw_scan.config import Settings
from uw_scan.storage.repository import Repository


def _test_settings() -> Settings:
    test_db = os.environ.get("UW_SCAN_TEST_DB_NAME")
    if not test_db:
        pytest.fail(
            "UW_SCAN_TEST_DB_NAME is not set.",
            pytrace=False,
        )
    os.environ.setdefault("UW_SCAN_API_KEY", "test-dummy-not-used-by-db-tests")
    return Settings.from_env().model_copy(update={"db_name": test_db})


@pytest.fixture
def app_with_seed(seeded_db_empty_cards) -> TestClient:
    # seeded_db_empty_cards drives the session migrate + per-test baseline
    # restore. Seed the macro series for the gauge endpoint into the same DB.
    settings = _test_settings()
    repo = seeded_db_empty_cards
    base = date(2025, 1, 1)
    for i in range(400):
        d = base + timedelta(days=i)
        repo.insert_macro_series_daily(
            "DFII10",
            d,
            Decimal(str(2.0 - i * 0.003)),
            datetime.combine(d, datetime.min.time(), tzinfo=UTC),
            None,
            "FRED",
            None,
        )
    repo.conn.commit()

    app = create_app()

    def _override_settings() -> Settings:
        return settings

    def _override_repo():
        conn = psycopg.connect(settings.db_dsn())
        try:
            yield Repository(conn, schema=settings.db_schema)
        finally:
            conn.close()

    app.dependency_overrides[get_settings] = _override_settings
    app.dependency_overrides[get_repo] = _override_repo
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_gauge_endpoint_returns_current_corr_history(
    app_with_seed: TestClient,
) -> None:
    response = app_with_seed.get("/api/gold/gauge")
    assert response.status_code == 200
    body = response.json()
    assert "current" in body
    assert "state" in body["current"]
    assert isinstance(body["history_60d"], list)
    assert isinstance(body["history_252d"], list)


def test_gauge_endpoint_bounds_series_and_history_to_replay_day_end(
    app_with_seed: TestClient,
) -> None:
    class RecordingRepo:
        def __init__(self) -> None:
            self.series_calls: list[dict[str, object]] = []
            self.history_call: dict[str, object] = {}

        def fetch_macro_series_daily(self, series_id: str, **kwargs):
            self.series_calls.append({"series_id": series_id, **kwargs})
            return []

        def fetch_gold_gauge_history(self, **kwargs):
            self.history_call = kwargs
            return []

    repo = RecordingRepo()
    app_with_seed.app.dependency_overrides[get_repo] = lambda: repo

    response = app_with_seed.get("/api/gold/gauge?as_of=2025-01-02")

    assert response.status_code == 200
    expected_instant = datetime(2025, 1, 2, 23, 59, 59, 999999, tzinfo=UTC)
    assert {call["to_date"] for call in repo.series_calls} == {date(2025, 1, 2)}
    assert {call["as_of_max"] for call in repo.series_calls} == {expected_instant}
    assert repo.history_call["to_date"] == date(2025, 1, 2)
    assert repo.history_call["as_of_max"] == expected_instant


def test_inputs_endpoint_returns_series_points(app_with_seed: TestClient) -> None:
    response = app_with_seed.get("/api/gold/inputs/DFII10?from=2025-01-01")
    assert response.status_code == 200
    body = response.json()
    assert body["series_id"] == "DFII10"
    assert len(body["points"]) > 100


def test_inputs_endpoint_replay_excludes_vintages_seen_after_day_end(
    app_with_seed: TestClient,
) -> None:
    app = app_with_seed.app
    settings = app.dependency_overrides[get_settings]()
    with psycopg.connect(settings.db_dsn()) as conn:
        repo = Repository(conn, schema=settings.db_schema)
        repo.insert_macro_series_daily(
            "DFII10",
            date(2025, 1, 1),
            Decimal("9.99"),
            datetime(2025, 1, 3, tzinfo=UTC),
            None,
            "FRED",
            None,
        )
        conn.commit()

    response = app_with_seed.get(
        "/api/gold/inputs/DFII10?from=2025-01-01&to=2025-01-01&as_of=2025-01-02"
    )

    assert response.status_code == 200
    points = response.json()["points"]
    assert [(point["obs_date"], point["value"]) for point in points] == [
        ("2025-01-01", "2.0")
    ]
    assert datetime.fromisoformat(points[0]["as_of"]).astimezone(UTC) == datetime(
        2025, 1, 1, tzinfo=UTC
    )


def test_inputs_endpoint_unknown_series_returns_empty(
    app_with_seed: TestClient,
) -> None:
    response = app_with_seed.get("/api/gold/inputs/NOPE")
    assert response.status_code == 200
    assert response.json()["points"] == []
