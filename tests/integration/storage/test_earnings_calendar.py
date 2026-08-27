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
  exactly the NULL-session-fills-in-later scenario this test exercises.
"""

from datetime import date

from uw_scan.storage.earnings_calendar import EarningsCalendarRepository

# Real event, frozen: NVDA reported Q2 FY2027 after the close on 2026-08-26
# (verified against the UW calendar at authoring time).
NVDA = {
    "ticker": "NVDA",
    "report_date": date(2026, 8, 26),
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
