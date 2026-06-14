"""GRG regime endpoint contract tests."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_grg_empty_when_no_snapshot(client: TestClient):
    resp = client.get("/api/regime/grg")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "empty"
    assert body["assets"] is None
    assert body["gates"] == []
    assert body["basis"] == "eod"
