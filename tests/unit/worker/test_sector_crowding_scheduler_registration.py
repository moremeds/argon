"""sector_crowding_capture cron wiring.

Locks the scheduler side: registers on a primary uw worker, and nowhere else.
A wrong group, a stale _is_primary_worker guard, or an unparseable crontab
string fails here rather than at 18:45 ET in production.
"""

from __future__ import annotations

import pytest

import uw_scan.worker.scheduler as scheduler

JOB_ID = "sector_crowding_capture"


class _StopStart(Exception):
    """Raised by the fake scheduler's start() to unwind main() after wiring."""


class _FakeSignal:
    SIGTERM = 15
    SIGINT = 2

    def signal(self, *_a, **_k) -> None:  # don't mutate the pytest process
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


def test_registered_on_primary_uw_worker(monkeypatch):
    ids = _registered_job_ids(
        monkeypatch,
        UW_SCAN_WORKER_ROLE="uw",
        UW_SCAN_WORKER_INDEX="0",
        UW_SCAN_WORKER_COUNT="1",
    )
    assert JOB_ID in ids


def test_not_registered_on_a_secondary_uw_shard(monkeypatch):
    """Two shards both firing would double the UW spend on the same 30 calls."""
    ids = _registered_job_ids(
        monkeypatch,
        UW_SCAN_WORKER_ROLE="uw",
        UW_SCAN_WORKER_INDEX="1",
        UW_SCAN_WORKER_COUNT="2",
    )
    assert JOB_ID not in ids


def test_not_registered_on_the_massive_worker(monkeypatch):
    """_is_primary_worker only checks role=='all' or index==0 -- it does NOT
    look at the group. The `if "uw" in groups:` block is what keeps this off
    the massive process, so index 0 here must still not register."""
    ids = _registered_job_ids(
        monkeypatch,
        UW_SCAN_WORKER_ROLE="massive",
        UW_SCAN_WORKER_INDEX="0",
        UW_SCAN_WORKER_COUNT="1",
    )
    assert JOB_ID not in ids
