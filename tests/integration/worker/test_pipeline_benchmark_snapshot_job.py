"""Regression: a heartbeat timestamped a hair AFTER now_utc (clock race) made
scheduler_heartbeat_lag_seconds negative, which violated the 058 CHECK (>= 0)
and dropped the whole benchmark snapshot (pipeline_benchmark_snapshots had 0
rows). The producer now clamps to max(0, ...); the constraint stays."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from uw_scan.benchmark.collector import build_pipeline_benchmark_inputs
from uw_scan.config import Settings

_NOW = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)


def _insert_heartbeat(repo, name: str, beat_at: datetime) -> None:
    with repo.conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {repo._schema}.worker_heartbeat (job_name, last_beat_at)
            VALUES (%s, %s)
            ON CONFLICT (job_name) DO UPDATE SET last_beat_at = EXCLUDED.last_beat_at
            """,
            (name, beat_at),
        )
    repo.conn.commit()


def _insert_snapshot(repo, lag, now):
    return repo.insert_pipeline_benchmark_snapshot(
        captured_at=now,
        capture_bucket=now,
        score=100,
        status="OK",
        freshness_score=100,
        coverage_score=100,
        throughput_score=100,
        provider_score=100,
        worker_score=100,
        persistence_score=100,
        scheduler_heartbeat_lag_seconds=lag,
    )


def test_future_heartbeat_lag_clamps_to_zero(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    # heartbeat lands 5s in the FUTURE relative to now_utc
    _insert_heartbeat(repo, "worker:uw:0", _NOW + timedelta(seconds=5))
    inputs = build_pipeline_benchmark_inputs(
        repo,
        Settings(api_key="test", uw_worker_count=1, massive_worker_count=1),
        now_utc=_NOW,
    )
    assert inputs.scheduler_heartbeat_lag_seconds == 0.0


def test_snapshot_persists_with_clamped_lag_and_constraint_is_real(
    seeded_db_empty_cards,
):
    repo = seeded_db_empty_cards
    sid = _insert_snapshot(repo, 0.0, _NOW)
    assert sid is not None
    # the 058 CHECK is real — a negative lag is rejected, which is exactly why
    # the producer must clamp rather than the migration relaxing the constraint.
    with pytest.raises(psycopg.errors.CheckViolation):
        _insert_snapshot(repo, -5.0, _NOW)
    repo.conn.rollback()
