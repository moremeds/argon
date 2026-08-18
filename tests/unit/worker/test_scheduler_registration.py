"""discovery_scan registration wiring.

The job function is exercised end-to-end elsewhere; this locks the *scheduler
wiring*: it registers only on a primary uw worker and only when the kill switch
is on. Boots the real ``scheduler.main()`` with a fake BlockingScheduler that
records job ids and aborts at ``start()`` (registration is pure — no DB/IO runs
before start), so a broken guard, a typo in the id, or an invalid cron string
would fail here.
"""

from __future__ import annotations

import pytest

import uw_scan.worker.scheduler as scheduler


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


def test_discovery_scan_registered_on_primary_uw_when_enabled(monkeypatch):
    ids = _registered_job_ids(
        monkeypatch,
        UW_SCAN_WORKER_ROLE="uw",
        UW_SCAN_WORKER_INDEX="0",
        UW_SCAN_WORKER_COUNT="1",
        SCANNER_DISCOVER_SCAN_ENABLED="true",
    )
    assert "discovery_scan" in ids


def test_discovery_scan_absent_when_disabled(monkeypatch):
    ids = _registered_job_ids(
        monkeypatch,
        UW_SCAN_WORKER_ROLE="uw",
        UW_SCAN_WORKER_INDEX="0",
        UW_SCAN_WORKER_COUNT="1",
        SCANNER_DISCOVER_SCAN_ENABLED="false",
    )
    assert "discovery_scan" not in ids
    # Harness sanity: a sibling uw job still registers when the switch is off.
    assert "full_scan_0" in ids


def test_discovery_scan_absent_on_non_primary_uw(monkeypatch):
    ids = _registered_job_ids(
        monkeypatch,
        UW_SCAN_WORKER_ROLE="uw",
        UW_SCAN_WORKER_INDEX="1",
        UW_SCAN_WORKER_COUNT="2",
        SCANNER_DISCOVER_SCAN_ENABLED="true",
    )
    assert "discovery_scan" not in ids


_UW_ALPHA_JOB_IDS = {
    "uw_alpha_gex_capture",
    "uw_alpha_volatility_capture",
    "uw_alpha_short_pressure_capture",
    "uw_alpha_intraday_flow_capture",
    "uw_alpha_dark_lit_capture",
}


def test_uw_alpha_capture_registered_on_primary_uw_when_enabled(monkeypatch):
    ids = _registered_job_ids(
        monkeypatch,
        UW_SCAN_WORKER_ROLE="uw",
        UW_SCAN_WORKER_INDEX="0",
        UW_SCAN_WORKER_COUNT="1",
        UW_SCAN_UW_ALPHA_CAPTURE_ENABLED="true",
    )
    assert _UW_ALPHA_JOB_IDS <= ids  # all five register


def test_uw_alpha_capture_absent_when_disabled(monkeypatch):
    ids = _registered_job_ids(
        monkeypatch,
        UW_SCAN_WORKER_ROLE="uw",
        UW_SCAN_WORKER_INDEX="0",
        UW_SCAN_WORKER_COUNT="1",
        UW_SCAN_UW_ALPHA_CAPTURE_ENABLED="false",
    )
    assert not (_UW_ALPHA_JOB_IDS & ids)  # none register
    assert "full_scan_0" in ids  # harness sanity: sibling uw job still wires


def test_uw_alpha_capture_absent_on_non_primary_uw(monkeypatch):
    ids = _registered_job_ids(
        monkeypatch,
        UW_SCAN_WORKER_ROLE="uw",
        UW_SCAN_WORKER_INDEX="1",
        UW_SCAN_WORKER_COUNT="2",
        UW_SCAN_UW_ALPHA_CAPTURE_ENABLED="true",
    )
    assert not (_UW_ALPHA_JOB_IDS & ids)  # pinned to uw-0 only


def test_fundamental_ingest_registered_on_primary_uw_when_enabled(monkeypatch):
    ids = _registered_job_ids(
        monkeypatch,
        UW_SCAN_WORKER_ROLE="uw",
        UW_SCAN_WORKER_INDEX="0",
        UW_SCAN_WORKER_COUNT="1",
        UW_SCAN_FUNDAMENTAL_INGEST_ENABLED="true",
    )
    assert "fundamental_ingest" in ids


def test_fundamental_ingest_absent_when_disabled(monkeypatch):
    ids = _registered_job_ids(
        monkeypatch,
        UW_SCAN_WORKER_ROLE="uw",
        UW_SCAN_WORKER_INDEX="0",
        UW_SCAN_WORKER_COUNT="1",
        UW_SCAN_FUNDAMENTAL_INGEST_ENABLED="false",
    )
    assert "fundamental_ingest" not in ids
    assert "full_scan_0" in ids  # harness sanity: sibling uw job still wires


def test_fundamental_ingest_absent_on_non_primary_uw(monkeypatch):
    # No advisory lock on this job, so a per-role-0 pin would run N copies and
    # multiply UW spend. uw-0 only.
    ids = _registered_job_ids(
        monkeypatch,
        UW_SCAN_WORKER_ROLE="uw",
        UW_SCAN_WORKER_INDEX="1",
        UW_SCAN_WORKER_COUNT="2",
        UW_SCAN_FUNDAMENTAL_INGEST_ENABLED="true",
    )
    assert "fundamental_ingest" not in ids


def test_fundamental_ingest_absent_on_massive_role(monkeypatch):
    # It spends UW calls; the massive workers must never pick it up.
    ids = _registered_job_ids(
        monkeypatch,
        UW_SCAN_WORKER_ROLE="massive",
        UW_SCAN_WORKER_INDEX="0",
        UW_SCAN_WORKER_COUNT="1",
        UW_SCAN_FUNDAMENTAL_INGEST_ENABLED="true",
    )
    assert "fundamental_ingest" not in ids
    assert "fundamental_refresh" in ids  # harness sanity: massive-0 sibling wires


def test_fundamental_concentration_capture_registered_on_primary_uw(monkeypatch):
    ids = _registered_job_ids(
        monkeypatch,
        UW_SCAN_WORKER_ROLE="uw",
        UW_SCAN_WORKER_INDEX="0",
        UW_SCAN_WORKER_COUNT="1",
        UW_SCAN_FUNDAMENTAL_CONCENTRATION_CAPTURE_ENABLED="true",
    )
    assert "fundamental_concentration_capture" in ids


def test_fundamental_concentration_capture_absent_when_disabled(monkeypatch):
    ids = _registered_job_ids(
        monkeypatch,
        UW_SCAN_WORKER_ROLE="uw",
        UW_SCAN_WORKER_INDEX="0",
        UW_SCAN_WORKER_COUNT="1",
        UW_SCAN_FUNDAMENTAL_CONCENTRATION_CAPTURE_ENABLED="false",
    )
    assert "fundamental_concentration_capture" not in ids
    assert "full_scan_0" in ids  # harness sanity: sibling uw job still wires


def test_fundamental_concentration_capture_absent_on_non_primary_uw(monkeypatch):
    # Same reason as the statement ingest: no advisory lock, so a per-role-0 pin
    # would run N copies of a 450-call job.
    ids = _registered_job_ids(
        monkeypatch,
        UW_SCAN_WORKER_ROLE="uw",
        UW_SCAN_WORKER_INDEX="1",
        UW_SCAN_WORKER_COUNT="2",
        UW_SCAN_FUNDAMENTAL_CONCENTRATION_CAPTURE_ENABLED="true",
    )
    assert "fundamental_concentration_capture" not in ids


def test_fundamental_concentration_capture_absent_on_massive_role(monkeypatch):
    # It spends UW calls; the massive workers must never pick it up.
    ids = _registered_job_ids(
        monkeypatch,
        UW_SCAN_WORKER_ROLE="massive",
        UW_SCAN_WORKER_INDEX="0",
        UW_SCAN_WORKER_COUNT="1",
        UW_SCAN_FUNDAMENTAL_CONCENTRATION_CAPTURE_ENABLED="true",
    )
    assert "fundamental_concentration_capture" not in ids
    assert "fundamental_refresh" in ids  # harness sanity: massive-0 sibling wires
