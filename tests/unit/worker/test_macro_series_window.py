"""The FRED request window, split by publication frequency.

FRED refuses a JSON ``series/observations`` request spanning more than 2000 vintage
dates.  The module's unbounded window is correct for monthly series and returns HTTP 400
for every daily one, which is how three of eleven series silently never ingested.
"""

from __future__ import annotations

from datetime import date

import pytest

from uw_scan.sources.fred_macro import SERIES_CONTRACT
from uw_scan.worker.jobs.macro_series_ingest import (
    ALL_VINTAGES_END,
    ALL_VINTAGES_START,
    DAILY_VINTAGE_START,
    DEFAULT_SERIES,
    request_window,
)

#: The FASTEST-minting daily series, not the average, because the cap is what the
#: fastest one hits first.  Measured against the live API on 2026-08-19 for DGS10 /
#: DFII10 / T10YIE (~248 a year: a 2019-01-01 start returned 1891 distinct vintages and
#: a 2021-01-01 start returned 1395) and again on 2026-08-21 for the plumbing series
#: added by MC3 -- SOFR 249.4, RRPONTSYD 248.7 and EFFR 250.7, the last of which is the
#: binding one at 2.3 years of headroom.  Taking the mean here would push the alarm past
#: the date EFFR actually starts returning HTTP 400.  Reproduce:
#: ``uv run python scripts/research/rates_market_layer_probe.py``.
VINTAGES_PER_YEAR = 251
FRED_VINTAGE_CAP = 2000


@pytest.mark.parametrize(
    "series_id", [s for s in DEFAULT_SERIES if SERIES_CONTRACT[s].frequency != "daily"]
)
def test_non_daily_series_keep_the_unbounded_vintage_window(series_id: str) -> None:
    # The window that makes a 1947 CPI vintage read as 1947. Narrowing it for these
    # would stamp the fetch date on decades of history.
    assert request_window(series_id, date(2015, 1, 1)) == (
        date(2015, 1, 1),
        ALL_VINTAGES_START,
        ALL_VINTAGES_END,
    )


@pytest.mark.parametrize(
    "series_id", [s for s in DEFAULT_SERIES if SERIES_CONTRACT[s].frequency == "daily"]
)
def test_daily_series_start_observations_where_the_vintages_start(
    series_id: str,
) -> None:
    obs_start, realtime_start, realtime_end = request_window(
        series_id, date(2015, 1, 1)
    )

    # Equality is the correctness condition, not a coincidence: an observation cannot be
    # published before the day it describes, so starting both on the same day means no
    # returned row has a true vintage outside the window and none can be clamped.
    assert obs_start == realtime_start == DAILY_VINTAGE_START
    assert realtime_end == ALL_VINTAGES_END


def test_a_caller_asking_for_less_history_still_gets_less() -> None:
    assert request_window("DGS10", date(2024, 1, 1))[0] == date(2024, 1, 1)


def test_an_unknown_series_gets_the_unbounded_window() -> None:
    # Loud failure over silent truncation: the unbounded window 400s on a daily series,
    # while guessing "daily" would quietly cut a monthly series' history to 2021.
    assert request_window("NOT_A_SERIES", date(2015, 1, 1)) == (
        date(2015, 1, 1),
        ALL_VINTAGES_START,
        ALL_VINTAGES_END,
    )


def test_daily_vintage_start_has_not_expired() -> None:
    """A deliberate deadline alarm: red build a year before FRED starts refusing.

    The 2000-vintage cap is on window WIDTH, so ``DAILY_VINTAGE_START`` is not a
    permanent value -- it buys ~8 years and then every daily series 400s again. This
    fails while there is still a year of headroom, so the renewal is scheduled work
    rather than an outage.  It is not flaky: it turns red once, on a knowable date.
    """
    elapsed_years = (date.today() - DAILY_VINTAGE_START).days / 365.25
    projected = elapsed_years * VINTAGES_PER_YEAR

    assert projected + VINTAGES_PER_YEAR < FRED_VINTAGE_CAP, (
        f"DAILY_VINTAGE_START={DAILY_VINTAGE_START} is within a year of FRED's "
        f"{FRED_VINTAGE_CAP}-vintage cap (~{projected:.0f} spanned today). Move it "
        "forward in macro_series_ingest.py -- and note it also raises the floor on how "
        "far back a macro state can be replayed."
    )
