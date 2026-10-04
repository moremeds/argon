"""Market-tide jobs must fail loudly so the job listener records the failure.

`_handle_job_event` records a failure (and drives the 3/10 streak alerts) only
when an exception leaves the job. The two market-tide closures used to catch,
log, roll back and return, so a failed run was recorded as a success. These
tests capture the real closures from `scheduler.main()` and check both paths.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime as real_datetime

import pytest

import uw_scan.scanners.market_tide as market_tide_scanner
import uw_scan.worker.jobs.market_tide_sentiment as sentiment_mod
import uw_scan.worker.schedule.regime as regime
import uw_scan.worker.scheduler as scheduler

_JOB_IDS = ("regime_market_tide_scan", "market_tide_sentiment_eod")


class _StopStart(Exception):
    pass


class _FakeSignal:
    SIGTERM = 15
    SIGINT = 2

    def signal(self, *_a, **_k) -> None:
        return None


class _WeekdayDatetime(real_datetime):
    """The tide scan returns early on weekends; pin `now()` to a Thursday so
    the test does not depend on the day it runs."""

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
def tide_jobs(monkeypatch):
    """Return (job_id -> closure, the fake repo every closure receives)."""
    captured: dict[str, object] = {}

    class _FakeSched:
        def __init__(self, *_a, **_k) -> None:
            pass

        def add_listener(self, *_a, **_k) -> None:
            pass

        def add_job(self, *args, **kwargs) -> None:
            if kwargs.get("id") in _JOB_IDS and args:
                captured[kwargs["id"]] = args[0]

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
    monkeypatch.setattr(regime, "datetime", _WeekdayDatetime)
    monkeypatch.setattr(regime, "_repo", fake_repo)
    monkeypatch.setattr(regime, "_external_api_recorder", fake_recorder)
    monkeypatch.setattr(regime, "_uw_client", lambda *a, **k: _FakeUwClient())
    monkeypatch.setenv("UW_SCAN_WORKER_ROLE", "uw")
    monkeypatch.setenv("UW_SCAN_WORKER_INDEX", "0")
    monkeypatch.setenv("UW_SCAN_WORKER_COUNT", "1")
    monkeypatch.setenv("MARKET_TIDE_CAPTURE_ENABLED", "true")

    with pytest.raises(_StopStart):
        scheduler.main()

    assert set(captured) == set(_JOB_IDS)
    return captured, repo


def test_tide_scan_failure_raises_after_rollback(tide_jobs, monkeypatch):
    jobs, repo = tide_jobs

    def boom(*_a, **_k):
        raise RuntimeError("uw 500")

    monkeypatch.setattr(market_tide_scanner, "run", boom)

    with pytest.raises(RuntimeError, match="uw 500"):
        jobs["regime_market_tide_scan"]()
    assert repo.conn.rollbacks == 1


def test_tide_scan_success_returns_normally(tide_jobs, monkeypatch):
    jobs, repo = tide_jobs
    calls = []

    def ok(*_a, **_k):
        calls.append(1)
        return 0  # zero bars (pre-open tick) is a normal outcome

    monkeypatch.setattr(market_tide_scanner, "run", ok)

    assert jobs["regime_market_tide_scan"]() is None
    assert calls == [1]
    assert repo.conn.rollbacks == 0


def test_tide_sentiment_failure_raises_after_rollback(tide_jobs, monkeypatch):
    jobs, repo = tide_jobs

    def boom(*_a, **_k):
        raise RuntimeError("db gone")

    monkeypatch.setattr(sentiment_mod, "refresh_eod_sentiment", boom)

    with pytest.raises(RuntimeError, match="db gone"):
        jobs["market_tide_sentiment_eod"]()
    assert repo.conn.rollbacks == 1


def test_tide_sentiment_success_returns_normally(tide_jobs, monkeypatch):
    jobs, repo = tide_jobs
    monkeypatch.setattr(sentiment_mod, "refresh_eod_sentiment", lambda *a, **k: 0)

    assert jobs["market_tide_sentiment_eod"]() is None
    assert repo.conn.rollbacks == 0
