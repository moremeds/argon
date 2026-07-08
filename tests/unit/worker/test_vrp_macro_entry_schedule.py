from __future__ import annotations

import pytest

import uw_scan.worker.scheduler as scheduler
from uw_scan.config import Settings
from uw_scan.worker.scheduler import _should_schedule_vrp_macro_entry

_ENTRY_IDS = {
    "vrp_macro_entry_rth",
    "vrp_macro_entry_eod",
    "vrp_macro_entry_postclose",
    "vrp_macro_entry_grid_refresh",
}


class _StopStart(Exception):
    pass


class _FakeSignal:
    SIGTERM = 15
    SIGINT = 2

    def signal(self, *_a, **_k) -> None:
        return None


def _registered_jobs(monkeypatch, **env) -> dict[str, dict]:
    jobs: dict[str, dict] = {}

    class _FakeSched:
        def __init__(self, *_a, **_k) -> None:
            pass

        def add_listener(self, *_a, **_k) -> None:
            pass

        def add_job(self, *_a, **kwargs) -> None:
            if kwargs.get("id"):
                entry = dict(kwargs)
                entry["_trigger"] = _a[1] if len(_a) > 1 else None
                jobs[kwargs["id"]] = entry

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
    return jobs


def _settings(**over) -> Settings:
    return Settings.from_env().model_copy(update=over)


def test_gate_false_when_disabled():
    s = _settings(
        vrp_macro_entry_capture_enabled=False, worker_role="massive", worker_index=0
    )
    assert _should_schedule_vrp_macro_entry(s) is False


def test_gate_true_on_massive_zero_and_all():
    assert _should_schedule_vrp_macro_entry(
        _settings(
            vrp_macro_entry_capture_enabled=True, worker_role="massive", worker_index=0
        )
    )
    assert _should_schedule_vrp_macro_entry(
        _settings(
            vrp_macro_entry_capture_enabled=True, worker_role="all", worker_index=3
        )
    )
    # not on a non-zero massive index, nor on a uw worker
    assert not _should_schedule_vrp_macro_entry(
        _settings(
            vrp_macro_entry_capture_enabled=True, worker_role="massive", worker_index=1
        )
    )
    assert not _should_schedule_vrp_macro_entry(
        _settings(
            vrp_macro_entry_capture_enabled=True, worker_role="uw", worker_index=0
        )
    )


def test_jobs_registered_on_massive_zero(monkeypatch):
    jobs = _registered_jobs(
        monkeypatch,
        UW_SCAN_WORKER_ROLE="massive",
        UW_SCAN_WORKER_INDEX="0",
        UW_SCAN_WORKER_COUNT="1",
    )
    assert _ENTRY_IDS <= set(jobs)
    for jid in _ENTRY_IDS:
        assert jobs[jid]["max_instances"] == 1
        assert jobs[jid]["coalesce"] is True


def test_jobs_absent_when_disabled(monkeypatch):
    jobs = _registered_jobs(
        monkeypatch,
        UW_SCAN_WORKER_ROLE="massive",
        UW_SCAN_WORKER_INDEX="0",
        UW_SCAN_WORKER_COUNT="1",
        UW_SCAN_VRP_MACRO_ENTRY_CAPTURE_ENABLED="false",
    )
    assert _ENTRY_IDS.isdisjoint(set(jobs))


def test_grid_refresh_fires_pre_market(monkeypatch):
    jobs = _registered_jobs(
        monkeypatch,
        UW_SCAN_WORKER_ROLE="massive",
        UW_SCAN_WORKER_INDEX="0",
        UW_SCAN_WORKER_COUNT="1",
    )
    trig = str(jobs["vrp_macro_entry_grid_refresh"]["_trigger"])
    # CronTrigger repr looks like: cron[minute='50', hour='3', ...]
    assert "hour='3'" in trig and "minute='50'" in trig
