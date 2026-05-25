from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime

from uw_scan.benchmark.pipeline import BenchmarkInputs
from uw_scan.config import Settings
from uw_scan.worker.jobs.pipeline_benchmark import pipeline_benchmark_snapshot_job


def test_pipeline_benchmark_snapshot_job_inserts_one_snapshot(monkeypatch) -> None:
    repo = _FakeRepo(lock_acquired=True)
    inputs = BenchmarkInputs(
        captured_at=datetime(2026, 5, 25, 12, 3, tzinfo=UTC),
        watchlist_size=4,
        scanner_fresh_count=3,
        scanner_stale_count=1,
        record_health_ok=True,
    )

    @contextmanager
    def fake_repo(_settings):
        yield repo

    monkeypatch.setattr("uw_scan.worker.jobs.pipeline_benchmark._repo", fake_repo)
    monkeypatch.setattr(
        "uw_scan.worker.jobs.pipeline_benchmark.build_pipeline_benchmark_inputs",
        lambda _repo, _settings, *, now_utc: inputs,
    )

    snapshot_id = pipeline_benchmark_snapshot_job(Settings(api_key="uw"))

    assert snapshot_id == 42
    assert repo.lock_calls == ["try", "release"]
    assert len(repo.insert_calls) == 1
    inserted = repo.insert_calls[0]
    assert inserted["capture_bucket"] == datetime(2026, 5, 25, 12, 0, tzinfo=UTC)
    assert inserted["watchlist_size"] == 4
    assert inserted["details_jsonb"]["bottleneck"] in {"freshness", "coverage"}
    assert inserted["details_jsonb"]["reasons"]


def test_pipeline_benchmark_snapshot_job_skips_when_lock_busy(monkeypatch) -> None:
    repo = _FakeRepo(lock_acquired=False)

    @contextmanager
    def fake_repo(_settings):
        yield repo

    monkeypatch.setattr("uw_scan.worker.jobs.pipeline_benchmark._repo", fake_repo)

    snapshot_id = pipeline_benchmark_snapshot_job(Settings(api_key="uw"))

    assert snapshot_id == 0
    assert repo.lock_calls == ["try"]
    assert repo.insert_calls == []


class _FakeRepo:
    def __init__(self, *, lock_acquired: bool) -> None:
        self.lock_acquired = lock_acquired
        self.lock_calls: list[str] = []
        self.insert_calls: list[dict] = []

    def try_advisory_lock(self, _key: int) -> bool:
        self.lock_calls.append("try")
        return self.lock_acquired

    def release_advisory_lock(self, _key: int) -> None:
        self.lock_calls.append("release")

    def insert_pipeline_benchmark_snapshot(self, **kwargs) -> int:
        self.insert_calls.append(kwargs)
        return 42
