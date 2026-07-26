"""Capture job: one UW in-outflow call plus one AUM refresh per ticker."""

from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from uw_scan.reports.sector_crowding import LOOKBACK_DAYS
from uw_scan.worker.jobs.sector_crowding_capture import (
    CAPTURE_TAIL_DAYS,
    sector_crowding_capture,
)


def _row(ticker: str, day: date):
    return SimpleNamespace(
        ticker=ticker,
        date=day,
        change=Decimal("1000"),
        change_prem=Decimal("2018212065"),
        close=Decimal("527.01"),
        volume=Decimal("10306265"),
    )


def test_captures_every_ticker_plus_the_benchmark():
    repo = MagicMock()
    repo.insert_scan_run.return_value = 42
    repo.insert_etf_flows_daily_rows.return_value = 1
    client = MagicMock()
    settings = SimpleNamespace(rth_tz="America/New_York")

    with patch("uw_scan.worker.jobs.sector_crowding_capture.uw_sources") as sources:
        sources.fetch_etf_in_outflow.side_effect = lambda **kw: [
            _row(kw["ticker"], date(2026, 7, 24))
        ]
        sources.fetch_etf_info.return_value = SimpleNamespace(
            aum=Decimal("45064294868")
        )
        sector_crowding_capture(repo=repo, client=client, settings=settings)

    called = {c.kwargs["ticker"] for c in sources.fetch_etf_in_outflow.call_args_list}
    assert "SPY" in called  # benchmark is required for every leg
    assert "SOXX" in called
    assert "XLK" in called
    assert "ARKK" not in called  # UW returns 0 rows for it
    assert len(called) == 15  # 14 sector ETFs + SPY


def test_one_bad_ticker_does_not_abort_the_run():
    repo = MagicMock()
    repo.insert_scan_run.return_value = 42
    repo.insert_etf_flows_daily_rows.return_value = 1
    client = MagicMock()
    settings = SimpleNamespace(rth_tz="America/New_York")

    def flaky(**kw):
        if kw["ticker"] == "XLE":
            raise RuntimeError("UW 429")
        return [_row(kw["ticker"], date(2026, 7, 24))]

    with patch("uw_scan.worker.jobs.sector_crowding_capture.uw_sources") as sources:
        sources.fetch_etf_in_outflow.side_effect = flaky
        sources.fetch_etf_info.return_value = SimpleNamespace(
            aum=Decimal("45064294868")
        )
        inserted = sector_crowding_capture(repo=repo, client=client, settings=settings)

    assert inserted == 14  # 15 attempted, XLE dropped
    # repo.conn.commit(), NOT repo.commit() -- Repository has no commit method;
    # every worker job commits through the connection. Asserting the wrong name
    # on a MagicMock passes silently, so this line is load-bearing.
    assert repo.conn.commit.called


def _spans(sources) -> set[int]:
    """Requested window width per ticker, in days."""
    return {
        (
            date.fromisoformat(c.kwargs["end_date"])
            - date.fromisoformat(c.kwargs["start_date"])
        ).days
        for c in sources.fetch_etf_in_outflow.call_args_list
    }


def _run(repo):
    client = MagicMock()
    settings = SimpleNamespace(rth_tz="America/New_York")
    with patch("uw_scan.worker.jobs.sector_crowding_capture.uw_sources") as sources:
        sources.fetch_etf_in_outflow.side_effect = lambda **kw: [
            _row(kw["ticker"], date(2026, 7, 24))
        ]
        sources.fetch_etf_info.return_value = SimpleNamespace(aum=Decimal("1"))
        sector_crowding_capture(repo=repo, client=client, settings=settings)
        return _spans(sources)


def test_populated_tail_pulls_only_the_short_window():
    """Steady state. Every run re-inserts its whole window under a fresh
    as_of, so the window width is a direct multiplier on table growth."""
    repo = MagicMock()
    repo.insert_scan_run.return_value = 42
    repo.insert_etf_flows_daily_rows.return_value = 1
    repo.fetch_etf_flows_daily.return_value = [{"obs_date": date(2026, 7, 23)}]

    assert _run(repo) == {CAPTURE_TAIL_DAYS}


def test_empty_tail_widens_to_full_history():
    """First run for a ticker, or recovery from an outage longer than the
    tail. Without the widen the percentile leg never accumulates the 60
    history points it needs and the price leg stays permanently None."""
    repo = MagicMock()
    repo.insert_scan_run.return_value = 42
    repo.insert_etf_flows_daily_rows.return_value = 1
    repo.fetch_etf_flows_daily.return_value = []

    assert _run(repo) == {LOOKBACK_DAYS}


def test_as_of_is_the_market_date_so_a_rerun_is_a_noop():
    """etf_flows_daily's conflict target is (ticker, obs_date, as_of). A
    wall-clock as_of makes every re-run a fresh key, so ON CONFLICT DO NOTHING
    never fires and worker/CLAUDE.md's run-twice-same-state rule is violated.
    Pin the stamp to midnight UTC of the capture date."""
    repo = MagicMock()
    repo.insert_scan_run.return_value = 42
    repo.insert_etf_flows_daily_rows.return_value = 1
    repo.fetch_etf_flows_daily.return_value = [{"obs_date": date(2026, 7, 23)}]

    _run(repo)

    stamps = {
        c.kwargs["as_of"] for c in repo.insert_etf_flows_daily_rows.call_args_list
    }
    assert len(stamps) == 1
    (as_of,) = stamps
    assert as_of.tzinfo is not None
    assert (as_of.hour, as_of.minute, as_of.second, as_of.microsecond) == (0, 0, 0, 0)
    assert as_of.date() == datetime.now(ZoneInfo("America/New_York")).date()


def test_scan_run_is_always_closed():
    """A raise from outside the per-ticker guards must not leave the run row at
    status='running' forever."""
    repo = MagicMock()
    repo.insert_scan_run.return_value = 42
    repo.fetch_etf_flows_daily.side_effect = RuntimeError("DB gone")
    client = MagicMock()
    settings = SimpleNamespace(rth_tz="America/New_York")

    with patch("uw_scan.worker.jobs.sector_crowding_capture.uw_sources"):
        # fetch_etf_flows_daily is inside the per-ticker try, so the sweep
        # survives it and returns 0 -> status 'fail', run still closed.
        sector_crowding_capture(repo=repo, client=client, settings=settings)

    repo.finish_scan_run.assert_called_once_with(42, status="fail")
