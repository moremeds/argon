
import pytest
from uw_scan.storage.cri_snapshot_repository import CriSnapshotRepository


def _payload(score: float, level: str, fired: bool) -> dict:
    return {
        "date": "2026-05-15",
        "vix": 18.43,
        "vvix": 92.9,
        "cor1m": 10.8,
        "spx_distance_pct": -2.5,
        "realized_vol": 14.2,
        "cri": {
            "score": score,
            "level": level,
            "components": {
                "vix": 5.0,
                "vvix": 4.0,
                "correlation": 3.0,
                "momentum": 2.5,
            },
        },
        "crash_trigger": {
            "fired": fired,
            "triggered": fired,
            "conditions": {},
            "values": {},
        },
        "cta": {
            "realized_vol": 14.2,
            "exposure_pct": 100.0,
            "forced_reduction_pct": 0.0,
        },
        "history": [],
        "spy_closes": [],
    }


def test_insert_returns_id_and_fetch_latest_roundtrip(seeded_db_empty_cards) -> None:
    repo = CriSnapshotRepository(
        seeded_db_empty_cards.conn,
        schema=seeded_db_empty_cards._schema,
    )
    rid = repo.insert_snapshot(payload=_payload(14.5, "LOW", False))
    assert rid > 0
    latest = repo.fetch_latest()
    assert latest is not None
    assert latest["cri"]["score"] == pytest.approx(14.5)
    assert latest["cri"]["level"] == "LOW"


def test_fetch_latest_returns_most_recent(seeded_db_empty_cards) -> None:
    repo = CriSnapshotRepository(
        seeded_db_empty_cards.conn,
        schema=seeded_db_empty_cards._schema,
    )
    repo.insert_snapshot(payload=_payload(20.0, "LOW", False))
    repo.insert_snapshot(payload=_payload(80.0, "CRITICAL", True))
    latest = repo.fetch_latest()
    assert latest["cri"]["level"] == "CRITICAL"
    assert latest["crash_trigger"]["fired"] is True


def test_fetch_history_returns_list_ascending(seeded_db_empty_cards) -> None:
    repo = CriSnapshotRepository(
        seeded_db_empty_cards.conn,
        schema=seeded_db_empty_cards._schema,
    )
    for score in (10.0, 30.0, 60.0):
        repo.insert_snapshot(payload=_payload(score, "LOW", False))
    rows = repo.fetch_history(limit=5)
    assert len(rows) == 3
    # Ascending by scanned_at — earliest first
    assert rows[0]["cri_score"] == pytest.approx(10.0)
    assert rows[-1]["cri_score"] == pytest.approx(60.0)


def test_fetch_latest_returns_none_when_empty(seeded_db_empty_cards) -> None:
    repo = CriSnapshotRepository(
        seeded_db_empty_cards.conn,
        schema=seeded_db_empty_cards._schema,
    )
    assert repo.fetch_latest() is None
