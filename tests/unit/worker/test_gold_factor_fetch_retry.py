import pytest

from uw_scan.sources.source_errors import SourceUnavailable
from uw_scan.worker.jobs import gold_factor as job

BARS = [("2026-10-09", 1.0)]


def _flaky(fail_times: int):
    calls = []

    def fetch(**kw):
        calls.append(kw["symbol"])
        if len(calls) <= fail_times:
            raise SourceUnavailable("xenon_query", "503 Service Unavailable")
        return BARS

    return fetch, calls


def test_retries_once_after_a_reset_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    fetch, calls = _flaky(1)
    monkeypatch.setattr(job, "fetch_ib_daily_midpoints", fetch)
    assert job._fetch_leg(0, symbol="XAUUSD") == BARS
    assert calls == ["XAUUSD", "XAUUSD"]


def test_second_failure_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    fetch, calls = _flaky(2)
    monkeypatch.setattr(job, "fetch_ib_daily_midpoints", fetch)
    with pytest.raises(SourceUnavailable):
        job._fetch_leg(0, symbol="XAUUSD")
    assert len(calls) == 2
