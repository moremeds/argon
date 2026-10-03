"""GEX / GRG / discovery jobs must fail loudly so the job listener records it.

`_handle_job_event` records a failure (and drives the 3/10 streak alerts) only
when an exception leaves the job. These closures used to catch, log and return,
so a failed run was recorded as a success. GEX is multi-unit (one unit per
ticker): it raises only when every ticker failed. These tests capture the real
closures from `scheduler.main()` and check each path.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime as real_datetime

import pytest

import uw_scan.scanners.gex as gex_scanner
import uw_scan.scanners.grg as grg_scanner
import uw_scan.worker.jobs.discovery_scan as discovery_mod
import uw_scan.worker.scheduler as scheduler

_JOB_IDS = ("regime_gex_scan", "regime_grg_scan", "discovery_scan")


class _StopStart(Exception):
    pass


class _FakeSignal:
    SIGTERM = 15
    SIGINT = 2

    def signal(self, *_a, **_k) -> None:
        return None


class _WeekdayDatetime(real_datetime):
    """The GEX scan returns early on weekends; pin `now()` to a Thursday."""

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
def jobs(monkeypatch):
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
    monkeypatch.setattr(scheduler, "datetime", _WeekdayDatetime)
    monkeypatch.setattr(scheduler, "_repo", fake_repo)
    monkeypatch.setattr(scheduler, "_external_api_recorder", fake_recorder)
    monkeypatch.setattr(scheduler, "_uw_client", lambda *a, **k: _FakeUwClient())
    monkeypatch.setattr(scheduler, "_research_budget_ok", lambda *a, **k: True)
    monkeypatch.setenv("UW_SCAN_WORKER_ROLE", "uw")
    monkeypatch.setenv("UW_SCAN_WORKER_INDEX", "0")
    monkeypatch.setenv("UW_SCAN_WORKER_COUNT", "1")
    monkeypatch.setenv("GEX_SCAN_TICKERS", "SPX,SPY,QQQ")
    monkeypatch.setenv("SCANNER_DISCOVER_SCAN_ENABLED", "true")

    with pytest.raises(_StopStart):
        scheduler.main()

    assert set(captured) == set(_JOB_IDS)
    return captured, repo


def test_gex_all_tickers_failed_raises(jobs, monkeypatch):
    closures, _repo = jobs
    calls: list[str] = []

    def boom(_uw, _repo, ticker):
        calls.append(ticker)
        raise RuntimeError(f"uw 500 {ticker}")

    monkeypatch.setattr(gex_scanner, "run", boom)

    with pytest.raises(RuntimeError, match="all 3 tickers failed") as info:
        closures["regime_gex_scan"]()
    assert calls == ["SPX", "SPY", "QQQ"]  # every ticker still tried
    assert "uw 500 QQQ" in str(info.value.__cause__)


def test_gex_partial_failure_returns_normally(jobs, monkeypatch):
    closures, _repo = jobs
    calls: list[str] = []

    def one_bad(_uw, _repo, ticker):
        calls.append(ticker)
        if ticker == "SPY":
            raise RuntimeError("uw 500 SPY")
        return 1

    monkeypatch.setattr(gex_scanner, "run", one_bad)

    assert closures["regime_gex_scan"]() is None
    assert calls == ["SPX", "SPY", "QQQ"]


def test_grg_failure_raises_after_rollback(jobs, monkeypatch):
    closures, repo = jobs

    def boom(*_a, **_k):
        raise RuntimeError("grg boom")

    monkeypatch.setattr(grg_scanner, "run", boom)

    with pytest.raises(RuntimeError, match="grg boom"):
        closures["regime_grg_scan"]()
    assert repo.conn.rollbacks == 1


def test_grg_success_returns_normally(jobs, monkeypatch):
    closures, repo = jobs
    monkeypatch.setattr(grg_scanner, "run", lambda *a, **k: 7)

    assert closures["regime_grg_scan"]() is None
    assert repo.conn.rollbacks == 0


def test_discovery_failure_raises_after_rollback(jobs, monkeypatch):
    closures, repo = jobs

    def boom(**_k):
        raise RuntimeError("alerts 500")

    monkeypatch.setattr(discovery_mod, "discovery_scan_once", boom)

    with pytest.raises(RuntimeError, match="alerts 500"):
        closures["discovery_scan"]()
    assert repo.conn.rollbacks == 1


def test_discovery_success_returns_normally(jobs, monkeypatch):
    closures, repo = jobs
    monkeypatch.setattr(
        discovery_mod, "discovery_scan_once", lambda **_k: {"status": "ok"}
    )

    assert closures["discovery_scan"]() is None
    assert repo.conn.rollbacks == 0
