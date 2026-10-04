"""The scheduled CFTC request window moves only when its content does.

``insert_macro_artifact`` treats ``source_url`` as immutable per content hash, so a start
date (and URL) that moved daily over unchanged bytes raised an identity collision.
"""

from datetime import date, timedelta

from uw_scan.sources.cftc_tff import _query_params
from uw_scan.worker.jobs.macro_market_layer_ingest import (
    DEFAULT_POSITIONING_LOOKBACK_DAYS,
    positioning_window_start,
)

TUE = date(2026, 9, 29)  # a Tuesday


def _start(day: date) -> date:
    return positioning_window_start(day, DEFAULT_POSITIONING_LOOKBACK_DAYS)


def test_start_is_always_a_tuesday_within_the_lookback() -> None:
    for offset in range(14):
        day = TUE + timedelta(days=offset)
        start = _start(day)
        assert start.weekday() == 1
        raw = day - timedelta(days=DEFAULT_POSITIONING_LOOKBACK_DAYS)
        assert raw - timedelta(days=6) <= start <= raw


def test_wednesday_moves_start_and_drops_exactly_one_report_date() -> None:
    wed = TUE + timedelta(days=1)
    before, after = _start(TUE), _start(wed)
    assert after - before == timedelta(days=7)
    # Only Tuesday-dated reports exist; exactly one leaves the window.
    dropped = [before + timedelta(days=7 * k) for k in range(20)]
    dropped = [d for d in dropped if before <= d < after]
    assert dropped == [before]
    assert _query_params(before) != _query_params(after)


def test_url_is_stable_from_wednesday_through_next_tuesday() -> None:
    wed = TUE + timedelta(days=1)
    params = {str(_query_params(_start(wed + timedelta(days=k)))) for k in range(7)}
    assert len(params) == 1
