from __future__ import annotations

from datetime import UTC, datetime, timedelta

from uw_scan.storage.repository import Repository


def test_pipeline_benchmark_snapshot_roundtrip(
    seeded_db_empty_cards: Repository,
) -> None:
    repo = seeded_db_empty_cards
    captured_at = datetime(2026, 5, 25, 12, 0, tzinfo=UTC)

    snapshot_id = repo.insert_pipeline_benchmark_snapshot(
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

    assert snapshot_id > 0
    latest = repo.get_latest_pipeline_benchmark_snapshot()
    assert latest is not None
    assert latest.score == 87
    assert latest.details_jsonb["bottleneck"] == "persistence"

    history = repo.list_pipeline_benchmark_snapshots(
        since=captured_at - timedelta(hours=1)
    )
    assert [row.id for row in history] == [snapshot_id]


def test_pipeline_benchmark_snapshot_bucket_is_unique(
    seeded_db_empty_cards: Repository,
) -> None:
    repo = seeded_db_empty_cards
    captured_at = datetime(2026, 5, 25, 12, 0, tzinfo=UTC)

    first_id = repo.insert_pipeline_benchmark_snapshot(
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
    )
    second_id = repo.insert_pipeline_benchmark_snapshot(
        captured_at=captured_at + timedelta(seconds=30),
        capture_bucket=captured_at,
        score=20,
        status="CRITICAL",
        freshness_score=20,
        coverage_score=20,
        throughput_score=20,
        provider_score=20,
        worker_score=20,
        persistence_score=20,
    )

    assert first_id == second_id
    assert len(repo.list_pipeline_benchmark_snapshots(since=captured_at)) == 1
