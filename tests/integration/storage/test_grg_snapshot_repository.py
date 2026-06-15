"""Round-trip tests for GrgSnapshotRepository (pytest-postgresql)."""

from __future__ import annotations

from datetime import date

from uw_scan.storage.grg_snapshot_repository import GrgSnapshotRepository


def test_insert_and_fetch_latest(seeded_db_empty_cards):
    repo = GrgSnapshotRepository(
        seeded_db_empty_cards.conn, schema=seeded_db_empty_cards._schema
    )
    payload = {
        "scan_time": "2026-06-12T19:37:41Z",
        "data_date": "2026-06-12",
        "signal": {
            "grg_z": -0.79,
            "interpretation": "RISK_OFF",
            "state": "RISK_OFF_DIVERGENCE",
            "tier": 3,
        },
        "assets": {
            "SPY": {"net_gamma": -702100.0},
            "TLT": {"net_gamma": 7700000.0},
        },
        "history": [{"date": "2026-06-11", "grg_z": -0.5}],
    }
    row_id = repo.insert_snapshot(payload=payload, data_date=date(2026, 6, 12))
    assert isinstance(row_id, int)

    latest = repo.fetch_latest()
    assert latest is not None
    assert latest["signal"]["grg_z"] == -0.79
    assert latest["assets"]["SPY"]["net_gamma"] == -702100.0
    assert latest["scan_time"] == "2026-06-12T19:37:41Z"


def test_fetch_latest_empty_returns_none(seeded_db_empty_cards):
    repo = GrgSnapshotRepository(
        seeded_db_empty_cards.conn, schema=seeded_db_empty_cards._schema
    )
    assert repo.fetch_latest() is None
