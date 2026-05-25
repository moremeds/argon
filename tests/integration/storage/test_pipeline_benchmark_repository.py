from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

from uw_scan.storage.repository import Repository

REPO_ROOT = Path(__file__).resolve().parents[3]


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
        last_full_scan_age_seconds=3600,
        queue_drain_rate_per_minute=1.25,
        details_jsonb={"bottleneck": "persistence"},
    )

    assert snapshot_id > 0
    latest = repo.get_latest_pipeline_benchmark_snapshot()
    assert latest is not None
    assert latest.score == 87
    assert latest.last_full_scan_age_seconds is not None
    assert float(latest.last_full_scan_age_seconds) == 3600
    assert latest.queue_drain_rate_per_minute is not None
    assert float(latest.queue_drain_rate_per_minute) == 1.25
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


def test_pipeline_benchmark_migration_repairs_existing_snapshot_table(
    seeded_db_empty_cards: Repository,
) -> None:
    repo = seeded_db_empty_cards
    with repo.conn.cursor() as cur:
        cur.execute(
            """
            ALTER TABLE uw_scan.pipeline_benchmark_snapshots
              DROP COLUMN IF EXISTS last_full_scan_age_seconds,
              DROP COLUMN IF EXISTS queue_drain_rate_per_minute
            """
        )
    repo.conn.commit()

    env = {**os.environ, "UW_SCAN_DB_NAME": os.environ["UW_SCAN_TEST_DB_NAME"]}
    subprocess.run(
        ["bash", str(REPO_ROOT / "scripts/migrate.sh")],
        check=True,
        cwd=REPO_ROOT,
        env=env,
    )

    with repo.conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'uw_scan'
              AND table_name = 'pipeline_benchmark_snapshots'
            """
        )
        columns = {row[0] for row in cur.fetchall()}

    assert "last_full_scan_age_seconds" in columns
    assert "queue_drain_rate_per_minute" in columns
    assert repo.list_pipeline_benchmark_snapshots(
        since=datetime.now(UTC) - timedelta(hours=1)
    ) == []
