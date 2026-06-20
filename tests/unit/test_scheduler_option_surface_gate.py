from __future__ import annotations

from types import SimpleNamespace

from uw_scan.worker.scheduler import _should_schedule_option_surface_capture


def _s(role: str, idx: int):
    return SimpleNamespace(worker_role=role, worker_index=idx)


def test_capture_pinned_to_uw_zero_or_all():
    assert _should_schedule_option_surface_capture(_s("all", 0)) is True
    assert _should_schedule_option_surface_capture(_s("uw", 0)) is True
    assert _should_schedule_option_surface_capture(_s("uw", 1)) is False
    assert _should_schedule_option_surface_capture(_s("massive", 0)) is False


def test_canary_import_and_wrapper_present():
    # The canary shares the capture gate (uw-0) — assert the job function imports cleanly.
    from uw_scan.worker.jobs.option_surface_iv_canary import option_surface_iv_canary

    assert callable(option_surface_iv_canary)
