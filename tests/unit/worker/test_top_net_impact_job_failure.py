"""The top-net-impact job must fail loudly so the job listener records it.

`_handle_job_event` records a failure (and drives the 3/10 streak alerts) only
when an exception leaves the job. The closure used to catch, log, roll back and
return, so a failed run was recorded as a success. These tests capture the real
closure from `scheduler.main()` and check both paths.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime as real_datetime

import pytest

import uw_scan.scanners.top_net_impact as top_net_impact_scanner
import uw_scan.worker.schedule.regime as regime
import uw_scan.worker.scheduler as scheduler

_JOB_ID = "regime_top_net_impact_scan"


class _StopStart(Exception):
    pass


class _FakeSignal:
    SIGTERM = 15
    SIGINT = 2

    def signal(self, *_a, **_k) -> None:
        return None


class _WeekdayDatetime(real_datetime):
    """The scan returns early on weekends; pin `now()` to a Thursday so the
    test does not depend on the day it runs."""

    @classmethod
    def now(cls, tz=None):
        return real_datetime(2026, 10, 1, 11, 0, tzinfo=tz)


class _FakeConn:
    def __init__(self) -> None:
        self.rollbacks = 0

    def rollback(self) -> None:
        self.rollbacks += 1


class _FakeRepo:
    def __init__(self) -> None:
        self.conn = _FakeConn()


class _FakeUwClient:
    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


@pytest.fixture
def tni_job(monkeypatch):
    """Return (the captured closure, the fake repo it receives)."""
    captured: dict[str, object] = {}

    class _FakeSched:
        def __init__(self, *_a, **_k) -> None:
            pass

        def add_listener(self, *_a, **_k) -> None:
            pass

        def add_job(self, *args, **kwargs) -> None:
            if kwargs.get("id") == _JOB_ID and args:
                captured["func"] = args[0]

        def start(self) -> None:
            raise _StopStart

        def shutdown(self, *_a, **_k) -> None:
            pass

    repo = _FakeRepo()

    @contextmanager
    def fake_repo(_settings):
        yield repo

    @contextmanager
    def fake_recorder(_settings):
        yield object()

    monkeypatch.setattr(scheduler, "BlockingScheduler", _FakeSched)
    monkeypatch.setattr(scheduler, "signal", _FakeSignal())
    monkeypatch.setattr(scheduler, "datetime", _WeekdayDatetime)
    monkeypatch.setattr(regime, "datetime", _WeekdayDatetime)
    monkeypatch.setattr(scheduler, "_repo", fake_repo)
    monkeypatch.setattr(regime, "_repo", fake_repo)
    monkeypatch.setattr(scheduler, "_external_api_recorder", fake_recorder)
    monkeypatch.setattr(regime, "_external_api_recorder", fake_recorder)
    monkeypatch.setattr(scheduler, "_uw_client", lambda *a, **k: _FakeUwClient())
    monkeypatch.setattr(regime, "_uw_client", lambda *a, **k: _FakeUwClient())
    monkeypatch.setenv("UW_SCAN_WORKER_ROLE", "uw")
    monkeypatch.setenv("UW_SCAN_WORKER_INDEX", "0")
    monkeypatch.setenv("UW_SCAN_WORKER_COUNT", "1")
    monkeypatch.setenv("TOP_NET_IMPACT_CAPTURE_ENABLED", "true")

    with pytest.raises(_StopStart):
        scheduler.main()

    assert "func" in captured
    return captured["func"], repo


def test_top_net_impact_failure_raises_after_rollback(tni_job, monkeypatch):
    job, repo = tni_job

    def boom(*_a, **_k):
        raise RuntimeError("uw 500")

    monkeypatch.setattr(top_net_impact_scanner, "run", boom)

    with pytest.raises(RuntimeError, match="uw 500"):
        job()
    assert repo.conn.rollbacks == 1


def test_top_net_impact_success_returns_normally(tni_job, monkeypatch):
    job, repo = tni_job
    calls = []

    def ok(*_a, **_k):
        calls.append(1)
        return 0  # zero rows (nothing published yet) is a normal outcome

    monkeypatch.setattr(top_net_impact_scanner, "run", ok)

    assert job() is None
    assert calls == [1]
    assert repo.conn.rollbacks == 0
