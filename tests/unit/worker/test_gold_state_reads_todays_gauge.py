"""The gold state must read a gauge computed for the day it answers for.

Gold's domain state calls ``fetch_gold_posture_as_of(as_of.date())`` -- the newest
posture row at or before the instant. The posture row for day D is written by
``gold_posture_compute``, whose target date is the latest ``GLD_CLOSE`` in the store,
so a run on the evening of D stamps ``obs_date = D``.

That makes the ORDER of the two crons the whole contract. If posture runs after the
state compute, the state can only ever find yesterday's row -- not on a bad night, but
every night, silently, with ``gauge_age_days`` honestly reporting a lag the schedule
itself created.

These tests lock the ordering rather than the clock times, so moving the block stays
free and inverting it does not.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

import uw_scan.worker.scheduler as scheduler


class _StopStart(Exception):
    """Raised by the fake scheduler's start() to unwind main() after wiring."""


class _FakeSignal:
    SIGTERM = 15
    SIGINT = 2

    def signal(self, *_a, **_k) -> None:
        return None


def _registered_triggers(monkeypatch, **env) -> dict[str, object]:
    found: dict[str, object] = {}

    class _FakeSched:
        def __init__(self, *_a, **_k) -> None:
            pass

        def add_listener(self, *_a, **_k) -> None:
            pass

        def add_job(self, *args, **kwargs) -> None:
            job_id = kwargs.get("id")
            trigger = kwargs.get("trigger") or (args[1] if len(args) > 1 else None)
            if job_id is not None and trigger is not None:
                found[job_id] = trigger

        def start(self) -> None:
            raise _StopStart

        def shutdown(self, *_a, **_k) -> None:
            pass

    monkeypatch.setattr(scheduler, "BlockingScheduler", _FakeSched)
    monkeypatch.setattr(scheduler, "signal", _FakeSignal())
    monkeypatch.setenv("UW_SCAN_DB_HOST", "127.0.0.1")
    monkeypatch.setenv("UW_SCAN_DB_NAME", "option_wizard_local")
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    with pytest.raises(_StopStart):
        scheduler.main()
    return found


@pytest.fixture
def triggers(monkeypatch) -> dict[str, object]:
    return _registered_triggers(
        monkeypatch,
        UW_SCAN_API_KEY="x",
        UW_SCAN_WORKER_ROLE="all",
        UW_SCAN_WORKER_INDEX="0",
        UW_SCAN_WORKER_COUNT="1",
        UW_SCAN_MACRO_STATE_COMPUTE_ENABLED="true",
    )


def _first_fire_on(trigger, day: datetime) -> datetime | None:
    """The trigger's first fire within ``day``, or None if it does not run that day."""
    start = day.replace(hour=0, minute=0, second=0, microsecond=0)
    nxt = trigger.get_next_fire_time(None, start - timedelta(seconds=1))
    if nxt is None or nxt >= start + timedelta(days=1):
        return None
    return nxt


#: A plain Wednesday. Every daily and Mon-Fri cron in the gold cascade fires.
WEDNESDAY = datetime(2026, 8, 26, tzinfo=ZoneInfo("America/New_York"))


def test_the_posture_is_computed_before_the_state_that_reads_it(triggers) -> None:
    posture = _first_fire_on(triggers["gold_posture_compute"], WEDNESDAY)
    state = _first_fire_on(triggers["macro_state_compute"], WEDNESDAY)

    assert posture is not None and state is not None
    assert posture < state, (
        f"gold_posture_compute fires at {posture:%H:%M} but macro_state_compute "
        f"reads it at {state:%H:%M}: the gold state can only ever see yesterday's gauge"
    )


def test_the_gpr_ingest_lands_before_the_posture_that_reads_it(triggers) -> None:
    # GPRD is the posture's only daily input that was scheduled after 18:30.
    gpr = _first_fire_on(triggers["gold_gpr_ingest"], WEDNESDAY)
    posture = _first_fire_on(triggers["gold_posture_compute"], WEDNESDAY)

    assert gpr is not None and posture is not None
    assert gpr < posture


def test_the_posture_waits_for_the_whole_daily_ingest_cascade(triggers) -> None:
    # Every series the posture reads must already be in the store. Naming them
    # here is the point: a new ingest added after the posture would go unnoticed.
    upstream = (
        "gold_fred_ingest",  # DFII10, T5YIFR, DTWEXBGS, CPIAUCSL, M2SL
        "gold_spot_ingest",  # GLD_CLOSE
        "gold_uw_options_ingest",
        "gold_comex_vault_ingest",
        "gold_etf_holdings_ingest",
        "gold_gpr_ingest",  # GPRD
    )
    posture = _first_fire_on(triggers["gold_posture_compute"], WEDNESDAY)

    for job_id in upstream:
        fire = _first_fire_on(triggers[job_id], WEDNESDAY)
        assert fire is not None, f"{job_id} does not run on a weekday"
        assert fire < posture, f"{job_id} fires at {fire:%H:%M}, after the posture"
