from __future__ import annotations

import pytest

import uw_scan.worker.scheduler as scheduler


class _StopStart(Exception):
    pass


class _FakeSignal:
    SIGTERM = 15
    SIGINT = 2

    def signal(self, *_a, **_k) -> None:
        return None


def _registered_job_ids(monkeypatch, **env) -> set[str]:
    ids: list[str] = []

    class _FakeSched:
        def __init__(self, *_a, **_k) -> None:
            pass

        def add_listener(self, *_a, **_k) -> None:
            pass

        def add_job(self, *_a, **kwargs) -> None:
            ids.append(kwargs.get("id"))

        def start(self) -> None:
            raise _StopStart

        def shutdown(self, *_a, **_k) -> None:
            pass

    monkeypatch.setattr(scheduler, "BlockingScheduler", _FakeSched)
    monkeypatch.setattr(scheduler, "signal", _FakeSignal())
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    with pytest.raises(_StopStart):
        scheduler.main()
    return {i for i in ids if i is not None}


def test_vrp_trading_jobs_registered_on_primary_massive(monkeypatch):
    ids = _registered_job_ids(
        monkeypatch,
        UW_SCAN_WORKER_ROLE="massive",
        UW_SCAN_WORKER_INDEX="0",
        UW_SCAN_WORKER_COUNT="1",
    )
    assert {
        "vrp_candidates_refresh",
        "vrp_paper_open",
        "vrp_paper_mark",
        "vrp_backtest_refresh",
    } <= ids
