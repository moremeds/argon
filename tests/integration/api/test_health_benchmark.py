from __future__ import annotations

from datetime import UTC, datetime


def test_health_benchmark_current_returns_score_and_reasons(
    client, seeded_db_empty_cards
) -> None:
    _ = seeded_db_empty_cards

    response = client.get("/api/health/benchmark/current")

    assert response.status_code == 200
    body = response.json()
    assert 0 <= body["score"] <= 100
    assert body["status"] in {"OK", "DEGRADED", "CRITICAL"}
    assert set(body["subscores"]) == {
        "freshness",
        "coverage",
        "throughput",
        "provider",
        "worker",
        "persistence",
    }
    assert body["metrics"]["watchlist_size"] is not None
    assert "reasons" in body
    assert "bottleneck" in body


def test_health_benchmark_history_returns_persisted_snapshots(
    client, seeded_db_empty_cards
) -> None:
    captured_at = datetime.now(UTC)
    seeded_db_empty_cards.insert_pipeline_benchmark_snapshot(
        captured_at=captured_at,
        capture_bucket=captured_at,
        score=87,
        status="OK",
        freshness_score=90,
        coverage_score=88,
        throughput_score=80,
        provider_score=91,
        worker_score=100,
        persistence_score=75,
        watchlist_size=102,
        scanner_fresh_count=91,
        scanner_stale_count=7,
        scanner_dead_count=4,
        scanner_never_scanned_count=0,
        details_jsonb={"bottleneck": "persistence"},
    )

    response = client.get("/api/health/benchmark/history?hours=24")

    assert response.status_code == 200
    snapshots = response.json()["snapshots"]
    assert len(snapshots) == 1
    assert snapshots[0]["score"] == 87
    assert snapshots[0]["details_jsonb"]["bottleneck"] == "persistence"


def test_health_benchmark_history_validates_hours(client, seeded_db_empty_cards) -> None:
    _ = seeded_db_empty_cards

    response = client.get("/api/health/benchmark/history?hours=999")

    assert response.status_code == 422
