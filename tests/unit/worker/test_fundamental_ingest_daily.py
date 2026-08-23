"""The daily job must spend nothing when nobody it cares about reported.

The universe is 450 names and ~6 report on an average day, so the intersection being
empty is the COMMON case, not an edge one — a job that pulled anyway would cost more
than the monthly sweep it replaces.
"""

from __future__ import annotations

from datetime import date

import pytest

from uw_scan.api.endpoints import EndpointSlug
from uw_scan.worker.jobs import fundamental_ingest_daily as mod

TODAY = date(2026, 8, 21)


class _Repo:
    def __init__(self, universe):
        self._universe = universe

    def list_universe(self, tier):
        return list(self._universe)


@pytest.fixture
def patched(monkeypatch):
    """Swap the two collaborators; record what each was asked for."""
    state = {"dates": [], "ingested": None, "calendar": {}}

    def fake_calendar(client, report_date, **_kw):
        state["dates"].append(report_date)
        return set(state["calendar"].get(report_date, ()))

    def fake_ingest(*, conn, client, tier, schema, tickers):
        state["ingested"] = list(tickers)
        return {
            "tickers": len(tickers),
            "inserted": 7,
            "touched": 1,
            "violations": 0,
            "failed": 0,
            "filing_date_tolerance": 2,
        }

    monkeypatch.setattr(mod, "fetch_calendar_symbols", fake_calendar)
    monkeypatch.setattr(mod, "fundamental_ingest", fake_ingest)
    monkeypatch.setattr(mod, "FundamentalObsRepository", lambda conn, schema: _Repo(state["universe"]))
    state["universe"] = {"AAPL", "NVDA", "WMT"}
    return state


def _run(state, **kw):
    return mod.fundamental_ingest_daily(conn=object(), client=object(), today=TODAY, **kw)


def test_only_universe_names_are_ingested(patched):
    patched["calendar"] = {TODAY: {"AAPL", "BEKE", "NVDA"}}
    out = _run(patched, lookback_days=0)

    assert patched["ingested"] == ["AAPL", "NVDA"], "BEKE is not in the universe"
    assert out["targets"] == 2
    assert out["calendar_symbols"] == 3
    assert out["inserted"] == 7


def test_nothing_relevant_reported_spends_no_ingest(patched):
    patched["calendar"] = {TODAY: {"BEKE", "KEEL"}}
    out = _run(patched, lookback_days=0)

    assert patched["ingested"] is None, "a non-universe calendar must not trigger a pull"
    assert out["targets"] == 0
    assert out["calendar_symbols"] == 2
    assert out["tickers"] == 0


def test_an_empty_universe_reads_no_calendar_at_all(patched):
    patched["universe"] = set()
    out = _run(patched, lookback_days=3)

    assert patched["dates"] == [], "an unseeded tier must spend zero UW calls"
    assert out == dict(mod._EMPTY)


def test_the_lookback_covers_a_weekend(patched):
    patched["calendar"] = {date(2026, 8, 18): {"WMT"}}
    out = _run(patched, lookback_days=3)

    assert patched["dates"] == [
        date(2026, 8, 21),
        date(2026, 8, 20),
        date(2026, 8, 19),
        date(2026, 8, 18),
    ]
    assert patched["ingested"] == ["WMT"], "a name missed on Tuesday is caught later"
    assert out["targets"] == 1


def test_a_name_reporting_twice_in_the_window_is_pulled_once(patched):
    patched["calendar"] = {TODAY: {"AAPL"}, date(2026, 8, 20): {"AAPL"}}
    _run(patched, lookback_days=1)
    assert patched["ingested"] == ["AAPL"]


def test_a_negative_lookback_still_reads_today(patched):
    patched["calendar"] = {TODAY: {"NVDA"}}
    _run(patched, lookback_days=-5)
    assert patched["dates"] == [TODAY]


def test_the_calendar_slots_are_the_registered_ones():
    """Guards the enum against a rename that would silently 404 every day."""
    from uw_scan.api.endpoints import REGISTRY
    from uw_scan.sources.earnings_calendar import SLOTS

    assert REGISTRY[EndpointSlug.EARNINGS_PREMARKET].path_template == "/api/earnings/premarket"
    assert REGISTRY[EndpointSlug.EARNINGS_AFTERHOURS].path_template == "/api/earnings/afterhours"
    assert set(SLOTS) <= set(REGISTRY)
