"""The daily job must spend nothing when nobody it cares about reported.

The universe is 450 names and ~6 report on an average day, so the intersection being
empty is the COMMON case, not an edge one — a job that pulled anyway would cost more
than the monthly sweep it replaces.

Also covers the durable-calendar persistence added for spec §5-i: every scanned date's
`fetch_calendar_listings` call is upserted into the calendar (real session, `uw_calendar`),
and a ticker that lands a NEW statement this run whose `filing_published_at` has no
matching calendar row gets the `session=NULL, source='statement_obs'` fallback.
"""

from __future__ import annotations

from datetime import date

import pytest

from uw_scan.api.endpoints import EndpointSlug
from uw_scan.sources.earnings_calendar import CalendarListing
from uw_scan.worker.jobs import fundamental_ingest_daily as mod

TODAY = date(2026, 8, 21)


class _Repo:
    def __init__(self, universe):
        self._universe = universe

    def list_universe(self, tier):
        return list(self._universe)


class _FakeCalendarRepo:
    """Stands in for `EarningsCalendarRepository`: records every `upsert_rows`
    call and answers `next_prints` from a pre-seeded 'already on the calendar'
    set, so the statement_obs skip-if-present branch is exercised without a
    real DB (see the module CLAUDE.md's isolation note — this file stays a
    pure-mock unit test on purpose)."""

    def __init__(self, existing):
        self.upserts: list[dict] = []
        self._existing = existing  # set[(ticker, date)]

    def upsert_rows(self, rows):
        rows = list(rows)
        self.upserts.extend(rows)
        # Mirrors the real repo's "genuinely new" semantics closely enough for
        # these tests: every row upserted here is new, since none of these
        # tests re-upsert the same (ticker, report_date) pair twice.
        return len(rows)

    def next_prints(self, *, on_or_after, tickers=None):
        # Matches the real repo's semantics: a row upserted earlier THIS run
        # (the calendar-listings persist, which happens before this method is
        # ever called) is already visible, same as a committed row would be
        # to a later query on the same connection.
        wanted = {t.upper() for t in tickers} if tickers is not None else None
        pool = set(self._existing) | {
            (r["ticker"], r["report_date"]) for r in self.upserts
        }
        return [
            {"ticker": t, "report_date": d}
            for (t, d) in pool
            if d >= on_or_after and (wanted is None or t in wanted)
        ]

    def prints_between(self, start, end):
        # Same pool as `next_prints` — a row seeded into `_existing` (a
        # pre-existing calendar row) or upserted earlier THIS run is visible.
        pool = set(self._existing) | {
            (r["ticker"], r["report_date"]) for r in self.upserts
        }
        return [{"ticker": t, "report_date": d} for (t, d) in pool if start <= d <= end]


@pytest.fixture
def patched(monkeypatch):
    """Swap the three collaborators; record what each was asked for."""
    state = {
        "dates": [],
        "ingested": None,
        "calendar": {},
        "existing_calendar": set(),
        "calendar_repo": None,
    }

    def fake_listings(client, report_date, **_kw):
        state["dates"].append(report_date)
        return [
            CalendarListing(symbol=symbol, session=session)
            for symbol, session in state["calendar"].get(report_date, ())
        ]

    def fake_ingest(*, conn, client, tier, schema, tickers):
        state["ingested"] = list(tickers)
        return {
            "tickers": len(tickers),
            "inserted": 7,
            "touched": 1,
            "violations": 0,
            "failed": 0,
            "filing_date_tolerance": 2,
            "new_filings": state.get("new_filings", []),
        }

    def fake_calendar_repo(conn, schema):
        repo = _FakeCalendarRepo(state["existing_calendar"])
        state["calendar_repo"] = repo
        return repo

    monkeypatch.setattr(mod, "fetch_calendar_listings", fake_listings)
    monkeypatch.setattr(mod, "fundamental_ingest", fake_ingest)
    monkeypatch.setattr(
        mod, "FundamentalObsRepository", lambda conn, schema: _Repo(state["universe"])
    )
    monkeypatch.setattr(mod, "EarningsCalendarRepository", fake_calendar_repo)
    state["universe"] = {"AAPL", "NVDA", "WMT"}
    return state


def _run(state, **kw):
    return mod.fundamental_ingest_daily(
        conn=object(), client=object(), today=TODAY, **kw
    )


def test_only_universe_names_are_ingested(patched):
    patched["calendar"] = {
        TODAY: [("AAPL", "premarket"), ("BEKE", "afterhours"), ("NVDA", "premarket")]
    }
    out = _run(patched, lookback_days=0)

    assert patched["ingested"] == ["AAPL", "NVDA"], "BEKE is not in the universe"
    assert out["targets"] == 2
    assert out["calendar_symbols"] == 3
    assert out["inserted"] == 7


def test_nothing_relevant_reported_spends_no_ingest(patched):
    patched["calendar"] = {TODAY: [("BEKE", "premarket"), ("KEEL", "afterhours")]}
    out = _run(patched, lookback_days=0)

    assert patched["ingested"] is None, (
        "a non-universe calendar must not trigger a pull"
    )
    assert out["targets"] == 0
    assert out["calendar_symbols"] == 2
    assert out["tickers"] == 0


def test_an_empty_universe_reads_no_calendar_at_all(patched):
    patched["universe"] = set()
    out = _run(patched, lookback_days=3)

    assert patched["dates"] == [], "an unseeded tier must spend zero UW calls"
    assert out == dict(mod._EMPTY)
    assert patched["calendar_repo"] is None, "no calendar repo is even constructed"


def test_the_lookback_covers_a_weekend(patched):
    patched["calendar"] = {date(2026, 8, 18): [("WMT", "premarket")]}
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
    patched["calendar"] = {
        TODAY: [("AAPL", "premarket")],
        date(2026, 8, 20): [("AAPL", "afterhours")],
    }
    _run(patched, lookback_days=1)
    assert patched["ingested"] == ["AAPL"]


def test_a_negative_lookback_still_reads_today(patched):
    patched["calendar"] = {TODAY: [("NVDA", "premarket")]}
    _run(patched, lookback_days=-5)
    assert patched["dates"] == [TODAY]


def test_the_calendar_slots_are_the_registered_ones():
    """Guards the enum against a rename that would silently 404 every day."""
    from uw_scan.api.endpoints import REGISTRY
    from uw_scan.sources.earnings_calendar import SLOTS

    assert (
        REGISTRY[EndpointSlug.EARNINGS_PREMARKET].path_template
        == "/api/earnings/premarket"
    )
    assert (
        REGISTRY[EndpointSlug.EARNINGS_AFTERHOURS].path_template
        == "/api/earnings/afterhours"
    )
    assert set(SLOTS) <= set(REGISTRY)


# ---------------------------------------------------------------------------
# Durable calendar persistence (spec §5-i)
# ---------------------------------------------------------------------------


def test_calendar_listings_are_persisted_with_real_session(patched):
    patched["calendar"] = {TODAY: [("AAPL", "premarket"), ("NVDA", "afterhours")]}
    out = _run(patched, lookback_days=0)

    repo = patched["calendar_repo"]
    assert {
        (r["ticker"], r["report_date"], r["session"], r["source"]) for r in repo.upserts
    } == {
        ("AAPL", TODAY, "premarket", "uw_calendar"),
        ("NVDA", TODAY, "afterhours", "uw_calendar"),
    }
    assert out["calendar_rows_new"] == 2


def test_calendar_rows_persist_even_when_no_target_matches(patched):
    """The calendar fetch/persist is a side effect of the fetch the job already
    pays for — it must not be gated on the tier intersection being non-empty."""
    patched["calendar"] = {TODAY: [("BEKE", "premarket")]}
    out = _run(patched, lookback_days=0)

    repo = patched["calendar_repo"]
    assert [(r["ticker"], r["report_date"], r["session"]) for r in repo.upserts] == [
        ("BEKE", TODAY, "premarket")
    ]
    assert out["calendar_rows_new"] == 1
    assert out["calendar_unknown_rows_new"] == 0


def test_a_new_filing_with_no_matching_calendar_row_lands_via_statement_obs(patched):
    """The ~2% UW reports `report_time: "unknown"` never appear in either
    classified slot, so they can never become a `fundamental_ingest_daily`
    target through the calendar intersection — their statement can only ever
    land via a caller (e.g. the monthly backstop sweep) that ingests them by
    tier membership rather than by calendar hit. This test proves the piece
    Task 5 owns: given ANY `new_filings` entry whose date has no calendar row
    — including one for a ticker absent from both slots this run, ISRG below —
    the fallback row lands with `session=NULL, source='statement_obs'`. The
    ticker that actually reaches `fundamental_ingest`'s `tickers=` argument is
    AAPL (it has to be, per the calendar-intersection gate); `new_filings` is
    it's own return channel and is asserted on directly, independent of which
    ticker was passed in — exactly the seam `fundamental_ingest_daily` owns.
    """
    patched["calendar"] = {TODAY: [("AAPL", "premarket")]}
    isrg_filing_date = date(2026, 7, 16)
    patched["new_filings"] = [
        {"ticker": "ISRG", "filing_published_at": isrg_filing_date}
    ]

    out = _run(patched, lookback_days=0)

    repo = patched["calendar_repo"]
    statement_obs_rows = [r for r in repo.upserts if r["source"] == "statement_obs"]
    assert statement_obs_rows == [
        {
            "ticker": "ISRG",
            "report_date": isrg_filing_date,
            "session": None,
            "source": "statement_obs",
        }
    ]
    assert out["calendar_unknown_rows_new"] == 1
    assert "new_filings" not in out, "internal plumbing must not leak into the summary"


def test_a_new_filing_matching_an_existing_calendar_row_is_left_alone(patched):
    """A ticker whose filing date coincides with a row the calendar ALREADY
    carries (from a prior run, or from this run's own listings upsert) must
    not get a redundant statement_obs row — the calendar row already carries
    the real session."""
    patched["calendar"] = {TODAY: [("AAPL", "premarket")]}
    patched["new_filings"] = [{"ticker": "AAPL", "filing_published_at": TODAY}]

    out = _run(patched, lookback_days=0)

    repo = patched["calendar_repo"]
    assert [r for r in repo.upserts if r["source"] == "statement_obs"] == []
    assert out["calendar_unknown_rows_new"] == 0


def test_a_new_filing_matching_a_pre_existing_calendar_row_is_left_alone(patched):
    """Same as above, but the matching row predates this run entirely (seeded
    into `next_prints`' answer set rather than upserted this run) — proves the
    existence check looks at the durable calendar, not just this run's own
    upserts."""
    patched["calendar"] = {TODAY: [("AAPL", "premarket")]}
    filing_date = date(2026, 7, 16)
    patched["existing_calendar"] = {("ISRG", filing_date)}
    patched["new_filings"] = [{"ticker": "ISRG", "filing_published_at": filing_date}]

    out = _run(patched, lookback_days=0)

    repo = patched["calendar_repo"]
    assert [r for r in repo.upserts if r["source"] == "statement_obs"] == []
    assert out["calendar_unknown_rows_new"] == 0


# ---------------------------------------------------------------------------
# C1 regression: the guard must key on a WINDOW around the filing date, not
# an exact match — the two clocks (filing date vs. real report date) differ
# for the normal case, which is exactly what let the phantom-row bug ship.
# ---------------------------------------------------------------------------


def test_a_classified_ticker_whose_filing_date_differs_from_its_report_date_is_left_alone(
    patched,
):
    """The C1 repro case, with real dates. ISRG's real Q2 FY2026 print is
    `report_date=2026-07-16` (verified live via UW `get_earnings_history`,
    `tests/integration/storage/test_earnings_calendar.py`'s `ISRG_KNOWN`
    fixture); its `filing_published_at` for the same period (period_end
    2026-06-30) is `2026-07-21` (real, queried from
    `option_wizard_local.uw_scan.fundamental_statement_obs` on 2026-08-28) —
    a **5-day gap between the two clocks**, the exact shape the branch review
    reproduced live: a calendar row keyed on the print date, and a filing
    date the daily job's guard used to compare bit-for-bit against it. Before
    the fix, this produced a second, phantom `statement_obs` row dated
    2026-07-21; the fix must recognize ISRG as already-known and write
    nothing."""
    isrg_report_date = date(2026, 7, 16)
    isrg_filing_date = date(2026, 7, 21)
    patched["calendar"] = {TODAY: [("AAPL", "premarket")]}
    patched["existing_calendar"] = {("ISRG", isrg_report_date)}
    patched["new_filings"] = [
        {"ticker": "ISRG", "filing_published_at": isrg_filing_date}
    ]

    out = _run(patched, lookback_days=0)

    repo = patched["calendar_repo"]
    assert [r for r in repo.upserts if r["source"] == "statement_obs"] == [], (
        "ISRG's real report_date (2026-07-16) is within the measured "
        "filing-to-print window of its real filing date (2026-07-21) and "
        "must be recognized as already known — no phantom row"
    )
    assert out["calendar_unknown_rows_new"] == 0


def test_a_filing_date_outside_the_measured_window_still_lands_via_statement_obs(
    patched,
):
    """The window has an edge: a filing date far enough from every existing
    calendar row (beyond `FILING_TO_PRINT_WINDOW_DAYS`) is genuinely unknown
    and must still land — the fix narrows the guard's blast radius, it does
    not turn it into a no-op that never fires. DJCO's real filing gap (see
    the filing-date-recovery VERDICT) is `period_end=2026-06-30`,
    `filing_published_at=2026-08-12`, with no calendar row anywhere near it
    (DJCO is one of the ~2% UW never classifies) — 100+ days from any
    existing print in this fixture, far outside the window."""
    djco_filing_date = date(2026, 8, 12)
    patched["calendar"] = {TODAY: [("AAPL", "premarket")]}
    patched["existing_calendar"] = {("ISRG", date(2026, 7, 16))}
    patched["new_filings"] = [
        {"ticker": "DJCO", "filing_published_at": djco_filing_date}
    ]

    out = _run(patched, lookback_days=0)

    repo = patched["calendar_repo"]
    assert [r for r in repo.upserts if r["source"] == "statement_obs"] == [
        {
            "ticker": "DJCO",
            "report_date": djco_filing_date,
            "session": None,
            "source": "statement_obs",
        }
    ]
    assert out["calendar_unknown_rows_new"] == 1
