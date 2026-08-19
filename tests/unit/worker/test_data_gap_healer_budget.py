"""Which nights the healer may spend the big UW cap on (pure logic, no DB).

The UW budget day runs 20:00 ET -> 20:00 ET and the healer fires AT 20:00, so a run
bills the day that FOLLOWS it. That one-day shift is the whole reason this needs a test:
the intuitive reading ("Saturday and Sunday are the weekend") would hand a full trading
Monday a 90k head start against a 105k account guard.
"""

from __future__ import annotations

from datetime import date, timedelta

from uw_scan.config import Settings
from uw_scan.worker.jobs.data_gap_healer import _nightly_uw_cap

_WEEKDAY = 30_000
_WEEKEND = 90_000


def _settings() -> Settings:
    return Settings.model_construct(
        data_gap_healer_max_uw_calls=_WEEKDAY,
        data_gap_healer_max_uw_calls_weekend=_WEEKEND,
    )


# 2026-08-17 is a Monday, so this week indexes cleanly off it.
_MON = date(2026, 8, 17)


def test_friday_and_saturday_runs_get_the_weekend_cap() -> None:
    # Friday's run bills Saturday, Saturday's bills Sunday — neither is a session.
    assert _nightly_uw_cap(_settings(), _MON + timedelta(days=4)) == _WEEKEND
    assert _nightly_uw_cap(_settings(), _MON + timedelta(days=5)) == _WEEKEND


def test_sunday_run_stays_on_the_weekday_cap() -> None:
    """The trap: Sunday night bills MONDAY, a full trading day."""
    sunday = _MON + timedelta(days=6)
    assert sunday.weekday() == 6
    assert _nightly_uw_cap(_settings(), sunday) == _WEEKDAY


def test_monday_through_thursday_get_the_weekday_cap() -> None:
    for offset in range(4):  # Mon, Tue, Wed, Thu
        assert _nightly_uw_cap(_settings(), _MON + timedelta(days=offset)) == _WEEKDAY


def test_cron_never_schedules_the_sunday_run() -> None:
    """Belt and braces: the weekday cap protects Monday, but the run should not fire.

    APScheduler's from_crontab maps day_of_week with Mon=0, so 0-5 is Mon-Sat.
    """
    assert Settings.model_fields["data_gap_healer_cron_et"].default == "0 20 * * 0-5"
