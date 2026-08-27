"""Per-print earnings reaction compute: calendar x daily_ohlc -> pct_move.

Uses a PRIVATE database (`option_wizard_test_reactions`), not the shared
`option_wizard_test` the rest of the integration suite resets per-fixture —
other sessions run integration tests against that shared DB concurrently, and
this file's fixtures create/drop schema state of their own. The private DB is
created (if absent) once per module and its schema is dropped+migrated fresh
per test, then the whole database is dropped at module teardown.

Fixture dates and closes verified live against Unusual Whales / the mini's
warm-store `daily_ohlc` at authoring time (2026-08-28):

- NVDA Q1 FY2027 (fiscal_date_ending 2026-04-30): `get_earnings_history`
  reports report_date=2026-05-20, report_time="postmarket" (afterhours).
  daily_ohlc closes: 2026-05-20 = 223.4700, 2026-05-21 = 219.5100 (queried
  from the mini's `option_wizard` warm store).
- NVDA Q4 FY2026 (fiscal_date_ending 2026-01-31): report_date=2026-02-25,
  report_time="postmarket". Closes: 2026-02-25 = 195.5600,
  2026-02-26 = 184.8900. Used alongside the Q1 print above to prove
  `last_reactions` returns newest-first over two real, distinct prints.
- NVDA Q2 FY2027 (fiscal_date_ending 2026-07-31): report_date=2026-08-26,
  report_time="postmarket" — this is the SAME real print already used as the
  NVDA fixture in `test_earnings_calendar.py`. As of authoring time the
  mini's daily_ohlc has NVDA's 2026-08-26 close (209.6600) but not yet
  2026-08-27 (the OHLC pull had not landed it) — a real, currently-missing
  after-close, used here to prove a print with no after-close writes nothing
  and is retried, not dropped.
- JPM Q2 FY2026 (fiscal_date_ending 2026-06-30): `get_earnings_history`
  reports report_date=2026-07-14, report_time="premarket", reported_eps=6.14
  vs estimated 5.59 (a real, already-reported event). Closes:
  2026-07-13 = 334.5300, 2026-07-14 = 342.8900.
- ISRG Q2 FY2026 (fiscal_date_ending 2026-06-30), report_date=2026-07-16:
  the SAME real print used in `test_earnings_calendar.py`, seeded here with
  `session=None` — the state UW's classified calendar actually carried for
  this print at 2026-08-23 (recorded in the filing-date-recovery verdict,
  since resolved to "postmarket"). Closes: 2026-07-15 = 388.9700,
  2026-07-17 = 345.4200 (2026-07-16 itself, the report day, deliberately not
  seeded — the NULL-session window never reads it: before wants < D and
  after wants > D).

No fabricated ticker, date, or price appears below.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import date

import psycopg
import pytest

from uw_scan.config import Settings
from uw_scan.storage.earnings_calendar import EarningsCalendarRepository
from uw_scan.storage.earnings_reactions import EarningsReactionsRepository
from uw_scan.storage.migrate_runner import apply_migrations
from uw_scan.worker.jobs.earnings_reactions import earnings_reactions_compute

_TEST_DB_NAME = "option_wizard_test_reactions"

# Real prints, frozen (see module docstring for verification provenance).
NVDA_MAY = {"ticker": "NVDA", "report_date": date(2026, 5, 20), "session": "afterhours"}
NVDA_FEB = {"ticker": "NVDA", "report_date": date(2026, 2, 25), "session": "afterhours"}
NVDA_AUG_PENDING = {
    "ticker": "NVDA",
    "report_date": date(2026, 8, 26),
    "session": "afterhours",
}
JPM_JUL = {"ticker": "JPM", "report_date": date(2026, 7, 14), "session": "premarket"}
ISRG_JUL = {"ticker": "ISRG", "report_date": date(2026, 7, 16), "session": None}


def _maint_settings() -> Settings:
    os.environ.setdefault("UW_SCAN_API_KEY", "test-dummy-not-used-by-db-tests")
    return Settings.from_env().model_copy(update={"db_name": "postgres"})


@pytest.fixture(scope="module")
def _reactions_settings() -> Iterator[Settings]:
    """Create the private test database once per module, migrate its schema
    fresh, and drop the whole database at module teardown. Never touches the
    shared `option_wizard_test` other sessions are resetting concurrently."""
    maint = _maint_settings()
    with psycopg.connect(maint.db_dsn(), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s", (_TEST_DB_NAME,)
            )
            if cur.fetchone() is None:
                cur.execute(f'CREATE DATABASE "{_TEST_DB_NAME}"')

    settings = maint.model_copy(update={"db_name": _TEST_DB_NAME})
    yield settings

    with psycopg.connect(maint.db_dsn(), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f'DROP DATABASE IF EXISTS "{_TEST_DB_NAME}"')


@pytest.fixture
def conn(_reactions_settings: Settings) -> Iterator[psycopg.Connection]:
    """Fresh schema per test — mirrors the shared suite's per-fixture
    DROP SCHEMA CASCADE, just against the private database."""
    with psycopg.connect(_reactions_settings.db_dsn(), autocommit=True) as admin:
        with admin.cursor() as cur:
            cur.execute("DROP SCHEMA IF EXISTS uw_scan CASCADE")
            cur.execute("CREATE SCHEMA uw_scan")
        apply_migrations(admin, log=lambda _msg: None)

    connection = psycopg.connect(_reactions_settings.db_dsn())
    try:
        yield connection
    finally:
        connection.close()


def _seed_ohlc(
    conn: psycopg.Connection, ticker: str, rows: list[tuple[str, float]]
) -> None:
    with conn.cursor() as cur:
        for d, close in rows:
            cur.execute(
                """INSERT INTO uw_scan.daily_ohlc (ticker, date, close, source)
                        VALUES (%s, %s, %s, 'massive.com')""",
                (ticker, date.fromisoformat(d), close),
            )
    conn.commit()


def _seed_calendar(conn: psycopg.Connection, *prints: dict) -> None:
    cal = EarningsCalendarRepository(conn, schema="uw_scan")
    cal.upsert_rows([{**p, "source": "uw_calendar"} for p in prints])


def test_afterhours_reaction_written_with_exact_pct_move(conn):
    """NVDA's real 2026-05-20 afterhours print: both closes present ->
    exactly one row, pct_move computed the same way the job computes it."""
    _seed_ohlc(conn, "NVDA", [("2026-05-20", 223.47), ("2026-05-21", 219.51)])
    _seed_calendar(conn, NVDA_MAY)

    result = earnings_reactions_compute(conn, as_of=date(2026, 5, 25))
    assert result == {"prints": 1, "written": 1, "skipped_incomplete": 0}

    repo = EarningsReactionsRepository(conn, schema="uw_scan")
    rows = repo.last_reactions("NVDA", n=4)
    assert len(rows) == 1
    row = rows[0]
    assert row["close_before_date"] == date(2026, 5, 20)
    assert row["close_after_date"] == date(2026, 5, 21)
    assert float(row["pct_move"]) == pytest.approx(219.51 / 223.47 - 1.0)


def test_premarket_reaction_before_strictly_prior_after_includes_report_day(conn):
    """JPM's real 2026-07-14 premarket print: before < D (2026-07-13's close),
    after >= D (2026-07-14's OWN close, since the report landed before open)."""
    _seed_ohlc(conn, "JPM", [("2026-07-13", 334.53), ("2026-07-14", 342.89)])
    _seed_calendar(conn, JPM_JUL)

    result = earnings_reactions_compute(conn, as_of=date(2026, 7, 20))
    assert result == {"prints": 1, "written": 1, "skipped_incomplete": 0}

    repo = EarningsReactionsRepository(conn, schema="uw_scan")
    row = repo.last_reactions("JPM", n=1)[0]
    assert row["close_before_date"] == date(2026, 7, 13)
    assert row["close_after_date"] == date(2026, 7, 14)  # the report day itself
    assert float(row["pct_move"]) == pytest.approx(342.89 / 334.53 - 1.0)


def test_null_session_reaction_uses_the_widest_window(conn):
    """ISRG seeded with session=None (the state UW's calendar carried for this
    print at 2026-08-23): before < D strictly, after > D strictly — the
    report day itself (2026-07-16) is deliberately never seeded and never
    read, because neither side of the NULL window includes it."""
    _seed_ohlc(conn, "ISRG", [("2026-07-15", 388.97), ("2026-07-17", 345.42)])
    _seed_calendar(conn, ISRG_JUL)

    result = earnings_reactions_compute(conn, as_of=date(2026, 7, 22))
    assert result == {"prints": 1, "written": 1, "skipped_incomplete": 0}

    repo = EarningsReactionsRepository(conn, schema="uw_scan")
    row = repo.last_reactions("ISRG", n=1)[0]
    assert row["session"] is None
    assert row["close_before_date"] == date(2026, 7, 15)
    assert row["close_after_date"] == date(2026, 7, 17)
    assert float(row["pct_move"]) == pytest.approx(345.42 / 388.97 - 1.0)


def test_missing_after_close_is_skipped_and_counted_and_retryable(conn):
    """NVDA's real, currently-open 2026-08-26 afterhours print: the mini's
    warm store has the before-close (2026-08-26 itself) but not yet the
    after-close (2026-08-27 had not landed via the OHLC pull as of authoring
    time). Nothing is written, the skip is counted, and a second run after
    the missing close lands resolves it — the calendar row is what makes the
    retry possible; nothing about the skip is destructive."""
    _seed_ohlc(conn, "NVDA", [("2026-08-26", 209.66)])
    _seed_calendar(conn, NVDA_AUG_PENDING)

    first = earnings_reactions_compute(conn, as_of=date(2026, 8, 28))
    assert first == {"prints": 1, "written": 0, "skipped_incomplete": 1}
    assert (
        EarningsReactionsRepository(conn, schema="uw_scan").last_reactions("NVDA", n=4)
        == []
    )

    # The missing close lands (simulating the next OHLC pull) -> retry resolves it.
    _seed_ohlc(conn, "NVDA", [("2026-08-27", 205.00)])
    second = earnings_reactions_compute(conn, as_of=date(2026, 8, 28))
    assert second == {"prints": 1, "written": 1, "skipped_incomplete": 0}
    resolved = EarningsReactionsRepository(conn, schema="uw_scan").last_reactions(
        "NVDA", n=4
    )
    assert len(resolved) == 1
    assert resolved[0]["close_after_date"] == date(2026, 8, 27)


def test_last_reactions_returns_newest_first(conn):
    """Two real, distinct NVDA prints (Feb and May 2026), both fully resolved
    -> `last_reactions` orders the more recent report_date first."""
    _seed_ohlc(
        conn,
        "NVDA",
        [
            ("2026-02-25", 195.56),
            ("2026-02-26", 184.89),
            ("2026-05-20", 223.47),
            ("2026-05-21", 219.51),
        ],
    )
    _seed_calendar(conn, NVDA_FEB, NVDA_MAY)

    result = earnings_reactions_compute(
        conn, as_of=date(2026, 5, 25), lookback_days=120
    )
    assert result == {"prints": 2, "written": 2, "skipped_incomplete": 0}

    rows = EarningsReactionsRepository(conn, schema="uw_scan").last_reactions(
        "NVDA", n=4
    )
    assert [r["report_date"] for r in rows] == [date(2026, 5, 20), date(2026, 2, 25)]


def test_rerun_is_idempotent_written_zero_on_replay(conn):
    """A second compute over the same window writes nothing new — `written`
    honestly reports zero (not `len(rows)`), matching the calendar
    repository's same insert-or-touch honesty rule."""
    _seed_ohlc(conn, "NVDA", [("2026-05-20", 223.47), ("2026-05-21", 219.51)])
    _seed_calendar(conn, NVDA_MAY)

    first = earnings_reactions_compute(conn, as_of=date(2026, 5, 25))
    assert first["written"] == 1
    second = earnings_reactions_compute(conn, as_of=date(2026, 5, 25))
    assert second == {"prints": 1, "written": 0, "skipped_incomplete": 0}


def test_reactions_for_groups_by_ticker_newest_first(conn):
    _seed_ohlc(conn, "NVDA", [("2026-05-20", 223.47), ("2026-05-21", 219.51)])
    _seed_ohlc(conn, "JPM", [("2026-07-13", 334.53), ("2026-07-14", 342.89)])
    _seed_calendar(conn, NVDA_MAY, JPM_JUL)
    earnings_reactions_compute(conn, as_of=date(2026, 7, 20), lookback_days=120)

    grouped = EarningsReactionsRepository(conn, schema="uw_scan").reactions_for(
        ["NVDA", "JPM", "AAPL"]
    )
    assert set(grouped) == {"NVDA", "JPM", "AAPL"}
    assert len(grouped["NVDA"]) == 1
    assert len(grouped["JPM"]) == 1
    assert grouped["AAPL"] == []
