"""The calendar accrues; a late-known session fills in and never regresses.

Fixture dates verified live against Unusual Whales at authoring time
(2026-08-27):
- NVDA: `get_upcoming_earnings`/`get_earnings_history` both show
  report_date=2026-08-26, report_time="postmarket" (afterhours) for the
  fiscal quarter ending 2026-07-31.
- ISRG: `get_earnings_history` shows report_date=2026-07-16, reported_eps=2.80
  vs estimated_eps=2.02 (a real, already-reported event) for the fiscal
  quarter ending 2026-06-30, report_time="postmarket" as of today. The
  filing-date-recovery verdict (2026-08-23) recorded this same event as
  calendar-absent at that time (report_time "unknown", missing from both the
  premarket and afterhours slots) — UW has since classified it, which is
  exactly the NULL-session-fills-in-later scenario the first test exercises.

No third ticker was introduced for the added `tickers=` filter / boundary
coverage below — NVDA and ISRG (both real, both frozen above) are sufficient
to prove restriction and boundary handling without fabricating a new fixture.
"""

from datetime import date, timedelta

from uw_scan.storage.earnings_calendar import EarningsCalendarRepository

# Real event, frozen: NVDA reported Q2 FY2027 after the close on 2026-08-26
# (verified against the UW calendar at authoring time).
NVDA = {
    "ticker": "NVDA",
    "report_date": date(2026, 8, 26),
    "session": "afterhours",
    "source": "uw_calendar",
}

# Real event, frozen: ISRG reported Q2 FY2026 after the close on 2026-07-16
# (verified against UW's earnings-history endpoint — reported_eps 2.80 vs
# estimated 2.02). `ISRG_KNOWN` is the resolved, fully-classified state used
# by the added tests below; the first test instead starts from the
# `session=None` state UW's calendar actually carried at 2026-08-23.
ISRG_KNOWN = {
    "ticker": "ISRG",
    "report_date": date(2026, 7, 16),
    "session": "afterhours",
    "source": "uw_calendar",
}


def _repo(seeded) -> EarningsCalendarRepository:
    return EarningsCalendarRepository(seeded.conn, schema=seeded._schema)


def test_upsert_accrues_and_null_session_fills_late(seeded_db_empty_cards):
    repo = _repo(seeded_db_empty_cards)
    unknown = {
        "ticker": "ISRG",
        "report_date": date(2026, 7, 16),
        "session": None,
        "source": "statement_obs",
    }
    assert repo.upsert_rows([NVDA, unknown]) == 2
    assert repo.upsert_rows([NVDA]) == 0  # touch, not insert
    # session becomes known later — must fill, and a NULL must never clobber
    assert (
        repo.upsert_rows([dict(unknown, session="afterhours", source="uw_calendar")])
        == 0
    )
    rows = repo.prints_between(date(2026, 7, 1), date(2026, 9, 1))
    by_t = {r["ticker"]: r for r in rows}
    assert by_t["ISRG"]["session"] == "afterhours"
    # a NULL must never clobber a known session — re-read AFTER the upsert
    assert repo.upsert_rows([dict(NVDA, session=None)]) == 0
    after = {
        r["ticker"]: r for r in repo.prints_between(date(2026, 7, 1), date(2026, 9, 1))
    }
    assert after["NVDA"]["session"] == "afterhours"
    assert {r["ticker"] for r in repo.next_prints(on_or_after=date(2026, 8, 20))} == {
        "NVDA"
    }


def test_next_prints_ticker_filter_restricts_and_excludes(seeded_db_empty_cards):
    """`tickers=` genuinely restricts the result set — a real qualifying row
    (ISRG, which is on-or-after the window same as NVDA) is excluded when it
    isn't named in the filter."""
    repo = _repo(seeded_db_empty_cards)
    repo.upsert_rows([NVDA, ISRG_KNOWN])

    # Without a ticker filter, both rows qualify by date alone.
    unfiltered = {r["ticker"] for r in repo.next_prints(on_or_after=date(2026, 7, 1))}
    assert unfiltered == {"NVDA", "ISRG"}

    # With the filter, only the named ticker comes back — ISRG is excluded
    # even though its report_date clears `on_or_after` just as NVDA's does.
    filtered = repo.next_prints(on_or_after=date(2026, 7, 1), tickers=["NVDA"])
    assert {r["ticker"] for r in filtered} == {"NVDA"}

    # Ticker matching is case-insensitive on the way in (upsert_rows and
    # next_prints both .upper() their ticker inputs).
    lowercase_filtered = repo.next_prints(
        on_or_after=date(2026, 7, 1), tickers=["nvda"]
    )
    assert {r["ticker"] for r in lowercase_filtered} == {"NVDA"}


def test_prints_between_is_inclusive_on_both_ends(seeded_db_empty_cards):
    """`report_date BETWEEN %s AND %s` is Postgres BETWEEN — inclusive on
    both the start and end bound. Proven directly: a query whose start (or
    end) equals a row's report_date includes that row, and shifting the
    bound one day past it excludes that row."""
    repo = _repo(seeded_db_empty_cards)
    repo.upsert_rows([NVDA, ISRG_KNOWN])

    isrg_date = ISRG_KNOWN["report_date"]
    nvda_date = NVDA["report_date"]

    # start == ISRG's report_date AND end == NVDA's report_date: both bounds
    # are hit exactly and both rows are included (both ends inclusive).
    exact_bounds = repo.prints_between(isrg_date, nvda_date)
    assert {r["ticker"] for r in exact_bounds} == {"NVDA", "ISRG"}

    # Narrowing the start past ISRG's date by one day excludes it.
    excludes_isrg = repo.prints_between(isrg_date + timedelta(days=1), nvda_date)
    assert {r["ticker"] for r in excludes_isrg} == {"NVDA"}

    # Narrowing the end past NVDA's date backward by one day excludes it.
    excludes_nvda = repo.prints_between(isrg_date, nvda_date - timedelta(days=1))
    assert {r["ticker"] for r in excludes_nvda} == {"ISRG"}

    # A range naming exactly one row's date on both ends returns only that row.
    exact_isrg = repo.prints_between(isrg_date, isrg_date)
    assert {r["ticker"] for r in exact_isrg} == {"ISRG"}


def test_upsert_normalizes_ticker_case(seeded_db_empty_cards):
    """A lowercase ticker on the way in is stored (and always read back)
    uppercase — `upsert_rows` calls `.upper()` on every row's ticker."""
    repo = _repo(seeded_db_empty_cards)
    lowercase_nvda = dict(NVDA, ticker="nvda")
    assert repo.upsert_rows([lowercase_nvda]) == 1

    rows = repo.prints_between(NVDA["report_date"], NVDA["report_date"])
    assert [r["ticker"] for r in rows] == ["NVDA"]
