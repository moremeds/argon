"""/api/scanner/discover — verifies sentinel scan_run row, ok/fail status, and
the earnings_unknown_dropped counter."""

from __future__ import annotations

import os
from typing import Any

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient

from uw_scan.api.deps import get_repo, get_settings, get_uw_client
from uw_scan.api.endpoints import EndpointSlug
from uw_scan.api.server import create_app
from uw_scan.config import Settings
from uw_scan.storage.repository import Repository


class _StubUwClient:
    def __init__(self, payload: dict[str, Any] | Exception) -> None:
        self._payload = payload

    def get(
        self,
        slug: EndpointSlug,
        ticker: str | None = None,
        params: dict[str, Any] | None = None,
        run_id: int | None = None,
    ) -> tuple[httpx.Response, dict[str, str]]:
        if isinstance(self._payload, Exception):
            raise self._payload
        return (
            httpx.Response(
                200,
                json=self._payload,
                request=httpx.Request("GET", "https://example/test"),
            ),
            {},
        )


def _ok_payload() -> dict[str, Any]:
    return {
        "data": [
            {
                "id": "a1",
                "ticker": "GFS",
                "type": "call",
                "strike": "120",
                "underlying_price": "118",
                "total_premium": "1500000",
                "total_ask_side_prem": "1200000",
                "total_bid_side_prem": "300000",
                "volume": 1500,
                "open_interest": 800,
                "has_multileg": False,
                "expiry": "2026-09-18",
                "next_earnings_date": "2026-08-04",
            },
            {
                # Will be dropped — next_earnings_date is missing
                "id": "a2",
                "ticker": "NVDA",
                "type": "call",
                "strike": "120",
                "underlying_price": "118",
                "total_premium": "1500000",
                "total_ask_side_prem": "1200000",
                "total_bid_side_prem": "300000",
                "volume": 1500,
                "open_interest": 800,
                "has_multileg": False,
                "expiry": "2026-09-18",
                "next_earnings_date": None,
            },
        ],
        "newer_than": None,
        "older_than": None,
    }


@pytest.fixture
def discover_client(request: pytest.FixtureRequest) -> TestClient:
    """TestClient with get_uw_client overridden by the requested stub.

    Use as: discover_client.__wrapped__(request, payload=...) won't work; pass
    via the indirect fixture pattern: ``@pytest.mark.parametrize('discover_client',
    [...], indirect=True)``.
    """
    payload = getattr(request, "param", _ok_payload())
    test_db = os.environ.get("UW_SCAN_TEST_DB_NAME")
    if not test_db:
        pytest.fail("UW_SCAN_TEST_DB_NAME not set", pytrace=False)
    os.environ.setdefault("UW_SCAN_API_KEY", "test-dummy")
    # Disable the freshness cache so each test sees a fresh UW round-trip;
    # otherwise a recent _DISCOVER row from a prior test would short-circuit
    # the route and break the `ok_before vs ok_after` invariant.
    settings = Settings.from_env().model_copy(
        update={"db_name": test_db, "scanner_discover_freshness_seconds": 0}
    )
    app = create_app()
    stub = _StubUwClient(payload)

    def _override_settings() -> Settings:
        return settings

    def _override_repo():
        conn = psycopg.connect(settings.db_dsn())
        try:
            yield Repository(conn, schema=settings.db_schema)
        finally:
            conn.close()

    def _override_client():
        return stub

    app.dependency_overrides[get_settings] = _override_settings
    app.dependency_overrides[get_repo] = _override_repo
    app.dependency_overrides[get_uw_client] = _override_client
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _count_discover_runs(test_db: str) -> tuple[int, int]:
    """Return (ok_count, fail_count) of _DISCOVER scan_runs rows."""
    settings = Settings.from_env().model_copy(update={"db_name": test_db})
    with (
        psycopg.connect(settings.db_dsn()) as conn,
        conn.cursor() as cur,
    ):
        cur.execute(
            "SELECT status, COUNT(*) FROM uw_scan.scan_runs WHERE ticker = '_DISCOVER' GROUP BY status"
        )
        rows = dict(cur.fetchall())
    return rows.get("ok", 0), rows.get("fail", 0)


def test_discover_happy_path_returns_candidates_and_writes_ok_run(
    discover_client: TestClient,
):
    test_db = os.environ["UW_SCAN_TEST_DB_NAME"]
    ok_before, fail_before = _count_discover_runs(test_db)

    resp = discover_client.get("/api/scanner/discover?limit=10&alerts_limit=50")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source"] == "market_wide_flow_alerts"
    assert body["alerts_pulled"] == 2
    assert body["earnings_unknown_dropped"] == 1, (
        "the NVDA alert with next_earnings_date=null must be counted"
    )

    ok_after, fail_after = _count_discover_runs(test_db)
    assert ok_after == ok_before + 1
    assert fail_after == fail_before


@pytest.mark.parametrize(
    "discover_client",
    [RuntimeError("boom: UW unreachable")],
    indirect=True,
)
def test_discover_fetch_failure_writes_fail_run_and_returns_502(
    discover_client: TestClient,
):
    test_db = os.environ["UW_SCAN_TEST_DB_NAME"]
    ok_before, fail_before = _count_discover_runs(test_db)

    resp = discover_client.get("/api/scanner/discover")

    assert resp.status_code == 502
    assert "flow-alerts" in resp.json()["detail"].lower()

    ok_after, fail_after = _count_discover_runs(test_db)
    assert ok_after == ok_before
    assert fail_after == fail_before + 1, "fail-status run must be persisted"


@pytest.fixture
def cached_discover_client(request: pytest.FixtureRequest) -> TestClient:
    """Same as discover_client but with the freshness cache ENABLED (60s)."""
    payload = getattr(request, "param", _ok_payload())
    test_db = os.environ.get("UW_SCAN_TEST_DB_NAME")
    if not test_db:
        pytest.fail("UW_SCAN_TEST_DB_NAME not set", pytrace=False)
    os.environ.setdefault("UW_SCAN_API_KEY", "test-dummy")
    settings = Settings.from_env().model_copy(
        update={"db_name": test_db, "scanner_discover_freshness_seconds": 60}
    )
    app = create_app()
    stub = _StubUwClient(payload)

    def _override_settings() -> Settings:
        return settings

    def _override_repo():
        conn = psycopg.connect(settings.db_dsn())
        try:
            yield Repository(conn, schema=settings.db_schema)
        finally:
            conn.close()

    def _override_client():
        return stub

    app.dependency_overrides[get_settings] = _override_settings
    app.dependency_overrides[get_repo] = _override_repo
    app.dependency_overrides[get_uw_client] = _override_client
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_discover_serves_from_freshness_cache_without_new_run(
    cached_discover_client: TestClient,
):
    """Two back-to-back GETs: first hits UW + writes run, second is served
    from the cached payload and writes NO new scan_run."""
    test_db = os.environ["UW_SCAN_TEST_DB_NAME"]

    # Prime: first call writes a run.
    resp1 = cached_discover_client.get("/api/scanner/discover")
    assert resp1.status_code == 200
    ok_after_first, _ = _count_discover_runs(test_db)

    # Hit cache: second call within freshness window must NOT create a new run.
    resp2 = cached_discover_client.get("/api/scanner/discover")
    assert resp2.status_code == 200
    ok_after_second, _ = _count_discover_runs(test_db)
    assert ok_after_second == ok_after_first, "cache hit should not insert another run"

    # Response shape parity (both derive from the same payload).
    assert resp2.json()["alerts_pulled"] == resp1.json()["alerts_pulled"]
    assert (
        resp2.json()["earnings_unknown_dropped"]
        == resp1.json()["earnings_unknown_dropped"]
    )
