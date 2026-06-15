"""GRG regime endpoint contract tests."""

from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

from uw_scan.storage.grg_snapshot_repository import GrgSnapshotRepository
from uw_scan.storage.repository import Repository


def test_grg_empty_when_no_snapshot(client: TestClient):
    resp = client.get("/api/regime/grg")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "empty"
    assert body["assets"] is None
    assert body["gates"] == []
    assert body["basis"] == "eod"
    # Empty response still carries the events shape (both lists empty).
    assert body["events"] == {"tops": [], "bottoms": []}


def test_grg_returns_events_when_snapshot_present(
    seeded_db_empty_cards: Repository, client: TestClient
):
    repo = seeded_db_empty_cards
    snap_repo = GrgSnapshotRepository(repo.conn, schema=repo._schema)
    payload = {
        "scan_time": "2026-06-12T19:37:41Z",
        "data_date": "2026-06-12",
        "basis": "eod",
        "signal": {"state": "RISK_OFF_DIVERGENCE", "grg_z": -0.79},
        "assets": {"SPY": {"ticker": "SPY"}, "TLT": {"ticker": "TLT"}},
        "events": {
            "tops": [],
            "bottoms": [
                {
                    "date": "2026-02-20",
                    "grg_z": -2.51,
                    "pair_state": "RISK_OFF_DIVERGENCE",
                    "tier": 2,
                    "spy_net_gamma": -2495996.0,
                    "tlt_net_gamma": 24012906.0,
                }
            ],
        },
    }
    snap_repo.insert_snapshot(payload=payload, data_date=date(2026, 6, 12))

    resp = client.get("/api/regime/grg")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["events"]["tops"] == []
    bottoms = body["events"]["bottoms"]
    assert len(bottoms) == 1
    assert bottoms[0]["date"] == "2026-02-20"
    assert bottoms[0]["pair_state"] == "RISK_OFF_DIVERGENCE"
    assert bottoms[0]["tier"] == 2
