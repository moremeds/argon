"""Nightly implied-move snapshot: option_surface_grid_daily -> Brenner-
Subrahmanyam ATM-straddle approximation (spec §5-iii).

Uses a PRIVATE database (`option_wizard_test_impliedmove`), not the shared
`option_wizard_test` the rest of the integration suite resets per-fixture —
other sessions run integration tests against that shared DB concurrently,
and this file's fixtures create/drop schema state of their own. Mirrors
`test_earnings_reactions.py`'s private-DB shape exactly.

FIXTURE PROVENANCE (queried live, 2026-08-28)
-----------------------------------------------
All option_surface_grid_daily rows below are REAL, frozen values pulled
ONCE from the dev warm store (`postgresql://argon_app@127.0.0.1/
option_wizard_local`, table `uw_scan.option_surface_grid_daily`) with:

    SELECT strike, call_iv, put_iv, underlying_spot
      FROM uw_scan.option_surface_grid_daily
     WHERE ticker = '<TICKER>' AND market_date = '2026-08-26'
       AND expiry = '<EXPIRY>'
     ORDER BY strike;

No strike, IV, or spot value below is invented, rounded, or interpolated —
every number is copy-pasted from that query's output. `market_date` for all
scenarios is `2026-08-26`, the only date this argon checkout's dev warm
store had accrued a full-chain snapshot for at authoring time (2026-08-28 is
"today" in this session, so no later snapshot could exist yet).

Calendar rows are REAL prints verified live via Unusual Whales
(`get_upcoming_earnings`) at authoring time, EXCEPT where noted below:

- AVGO: `get_upcoming_earnings` reports report_date=2026-09-02,
  report_time="postmarket" -> afterhours, reaction day = report_date + 1 =
  2026-09-03. Grid: spot=358.3500. THREE too-early expiries seeded
  (2026-08-26, 2026-08-31, 2026-09-04 -- wait, 2026-09-04 is the real
  covering expiry, not too-early; the too-early set is 2026-08-26 and
  2026-08-31) plus the covering expiry 2026-09-04 (first real expiry >=
  2026-09-03). Nearest strike at 2026-09-04 is 357.5
  (|358.35-357.5|=0.85 vs |360-358.35|=1.65).
- ADBE: report_date=2026-09-10, report_time="postmarket" -> afterhours,
  reaction day = 2026-09-11. Grid: spot=277.0200. Expiries 2026-09-04 (too
  early) and 2026-09-11 (the real covering expiry -- an EXACT boundary hit:
  reaction day equals the expiry itself, proving the `>=` is inclusive, not
  `>`). Nearest strike at 2026-09-11 is 277.5.
- ORCL: report_date=2026-09-08, report_time="unknown" -> session=None. Used
  with ZERO seeded option_surface_grid_daily rows (ORCL is not itself in
  argon's watchlist-driven surface capture), to prove the no-surface-rows
  case produces no row.
- MSFT (separate, standalone test): report_date=2026-11-04, report_time=
  "unknown" -> session=None. Used with as_of=2026-10-20 (within the 21-day
  lookahead of this real report_date) and zero seeded surface rows.

DEVIATION -- CRWV's calendar pairing is CONSTRUCTED, not a live UW calendar
fact. CRWV's grid row (expiry=2027-01-15, strike=28, call_iv=
1.13983701509183, put_iv=NULL, spot=92.5500) is the ONLY row anywhere in the
entire 2026-08-26 snapshot, across every ticker on the grid, missing exactly
one side of the smile at a strike (verified by scanning the whole table) --
it is the one real fixture that can prove the one-sided `iv_basis=
'call_only'` path without inventing an IV value. But CRWV's real next print
(`get_upcoming_earnings`: report_date=2026-11-09, report_time="unknown") is
75 days out, past the 21-day lookahead from 2026-08-26, the only market_date
this session's surface snapshot covers -- no real print for ANY ticker whose
2026-08-26 grid has a one-sided-IV row falls inside that window (checked:
zero one-sided rows exist among the 15 real in-window reporters this file
otherwise uses). The calendar row below (report_date=2026-09-05,
session=None) is therefore a chosen test date, not a UW fact, used solely to
route this real, frozen surface row through the job within the one window
available. No strike, IV, or spot is invented -- only the report_date is a
test construct, and it is called out here rather than passed off as live.

No fabricated ticker, strike, IV, or spot appears below.
"""

from __future__ import annotations

import math
import os
from collections.abc import Iterator
from datetime import date
from decimal import Decimal

import psycopg
import pytest

from uw_scan.config import Settings
from uw_scan.storage.earnings_calendar import EarningsCalendarRepository
from uw_scan.storage.implied_move import ImpliedMoveRepository
from uw_scan.storage.migrate_runner import apply_migrations
from uw_scan.worker.jobs.implied_move_snapshot import (
    BRENNER_SUBRAHMANYAM_CONSTANT,
    implied_move_snapshot,
)

_TEST_DB_NAME = "option_wizard_test_impliedmove"
_MARKET_DATE = date(2026, 8, 26)


def _maint_settings() -> Settings:
    os.environ.setdefault("UW_SCAN_API_KEY", "test-dummy-not-used-by-db-tests")
    return Settings.from_env().model_copy(update={"db_name": "postgres"})


@pytest.fixture(scope="module")
def _implied_move_settings() -> Iterator[Settings]:
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
def conn(_implied_move_settings: Settings) -> Iterator[psycopg.Connection]:
    with psycopg.connect(_implied_move_settings.db_dsn(), autocommit=True) as admin:
        with admin.cursor() as cur:
            cur.execute("DROP SCHEMA IF EXISTS uw_scan CASCADE")
            cur.execute("CREATE SCHEMA uw_scan")
        apply_migrations(admin, log=lambda _msg: None)

    connection = psycopg.connect(_implied_move_settings.db_dsn())
    try:
        yield connection
    finally:
        connection.close()


def _seed_grid_row(
    conn: psycopg.Connection,
    ticker: str,
    expiry: date,
    strike: float,
    call_iv: float | None,
    put_iv: float | None,
    spot: float,
    *,
    market_date: date = _MARKET_DATE,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO uw_scan.option_surface_grid_daily
                        (ticker, market_date, expiry, strike, call_iv, put_iv,
                         underlying_spot)
                 VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (ticker, market_date, expiry, strike, call_iv, put_iv, spot),
        )
    conn.commit()


def _seed_calendar(conn: psycopg.Connection, *prints: dict) -> None:
    cal = EarningsCalendarRepository(conn, schema="uw_scan")
    cal.upsert_rows([{**p, "source": "uw_calendar"} for p in prints])


def _seed_avgo_grid(
    conn: psycopg.Connection, *, market_date: date = _MARKET_DATE
) -> None:
    """Real AVGO 2026-08-26 rows: two too-early expiries (2026-08-26 itself,
    an expiring-today extreme-IV row, and 2026-08-31) + the real covering
    expiry 2026-09-04 (first expiry >= reaction day 2026-09-03)."""
    spot = 358.3500
    too_early = {
        date(2026, 8, 26): [
            (355, 13.1136232997271, 12.6423544768043),
            (357.5, 12.5359635200552, 15.3937760514078),
            (360, 13.3906137518894, 15.2748990404372),
        ],
        date(2026, 8, 31): [
            (355, 0.413732908741587, 0.405837839966126),
            (357.5, 0.416867211848913, 0.39787368859611),
            (360, 0.41869827629254, 0.395626701802496),
        ],
    }
    for expiry, rows in too_early.items():
        for strike, call_iv, put_iv in rows:
            _seed_grid_row(
                conn,
                "AVGO",
                expiry,
                strike,
                call_iv,
                put_iv,
                spot,
                market_date=market_date,
            )
    for strike, call_iv, put_iv in [
        (355, 0.737247726066368, 0.706432830617669),
        (357.5, 0.736661443735852, 0.706997006724508),
        (360, 0.736479134439724, 0.706456776805408),
    ]:
        _seed_grid_row(
            conn,
            "AVGO",
            date(2026, 9, 4),
            strike,
            call_iv,
            put_iv,
            spot,
            market_date=market_date,
        )


def _seed_adbe_grid(conn: psycopg.Connection) -> None:
    spot = 277.0200
    for strike, call_iv, put_iv in [
        (270, 0.481833526947137, 0.469581698886116),
        (272.5, 0.471153418043504, 0.470219523479023),
        (275, 0.483562345378973, 0.474253386969831),
        (277.5, 0.489636873100045, 0.471181251532029),
        (280, 0.489051973051219, 0.460798182444378),
    ]:
        _seed_grid_row(conn, "ADBE", date(2026, 9, 4), strike, call_iv, put_iv, spot)
    for strike, call_iv, put_iv in [
        (275, 0.631728802112195, 0.59617655423161),
        (277.5, 0.628767649021267, 0.595923605591813),
        (280, 0.623167798368051, 0.592541594140754),
    ]:
        _seed_grid_row(conn, "ADBE", date(2026, 9, 11), strike, call_iv, put_iv, spot)


def _expected_move(
    call_iv: float, put_iv: float | None, t_days: int
) -> tuple[float, str]:
    """Recomputes the formula independently in the test (never hardcodes a
    magic constant beyond the documented 0.7979) so a change to the real
    implementation's arithmetic -- not just its wiring -- would show up."""
    if put_iv is None:
        atm_iv, basis = call_iv, "call_only"
    else:
        atm_iv, basis = (call_iv + put_iv) / 2, "both"
    pct = BRENNER_SUBRAHMANYAM_CONSTANT * atm_iv * math.sqrt(t_days / 365.0)
    return pct, basis


def test_avgo_covering_expiry_skips_multiple_too_early_candidates(conn):
    """AVGO, session=afterhours -> reaction day = report_date + 1 =
    2026-09-03. Two too-early expiries (2026-08-26, 2026-08-31) are on the
    grid too -- the covering pick must skip both and land on 2026-09-04."""
    _seed_avgo_grid(conn)
    _seed_calendar(
        conn,
        {"ticker": "AVGO", "report_date": date(2026, 9, 2), "session": "afterhours"},
    )

    result = implied_move_snapshot(conn, as_of=_MARKET_DATE, schema="uw_scan")
    assert result == {"prints_upcoming": 1, "covered": 1, "not_covered": 0}

    row = ImpliedMoveRepository(conn, schema="uw_scan").latest_for(["AVGO"])["AVGO"]
    assert row["expiry"] == date(2026, 9, 4)
    assert row["strike"] == Decimal("357.5")
    assert row["iv_basis"] == "both"
    expected_pct, _ = _expected_move(0.736661443735852, 0.706997006724508, 9)
    assert float(row["implied_move_pct"]) == pytest.approx(expected_pct)
    assert float(row["implied_move_usd"]) == pytest.approx(expected_pct * 358.3500)


def test_adbe_afterhours_reaction_day_is_exact_expiry_boundary(conn):
    """ADBE, session=afterhours -> reaction day = report_date + 1 =
    2026-09-11, which is ITSELF an expiry on the grid. This is the sharpest
    possible test of the `>=` in the covering-expiry filter: a `>` mutant
    would skip 2026-09-11 and, since nothing later is seeded, would flip
    this to not_covered rather than just picking a different date."""
    _seed_adbe_grid(conn)
    _seed_calendar(
        conn,
        {"ticker": "ADBE", "report_date": date(2026, 9, 10), "session": "afterhours"},
    )

    result = implied_move_snapshot(conn, as_of=_MARKET_DATE, schema="uw_scan")
    assert result == {"prints_upcoming": 1, "covered": 1, "not_covered": 0}

    row = ImpliedMoveRepository(conn, schema="uw_scan").latest_for(["ADBE"])["ADBE"]
    assert row["expiry"] == date(2026, 9, 11)
    assert row["strike"] == Decimal("277.5")
    expected_pct, _ = _expected_move(0.628767649021267, 0.595923605591813, 16)
    assert float(row["implied_move_pct"]) == pytest.approx(expected_pct)


def test_one_sided_put_iv_null_uses_call_only_basis(conn):
    """CRWV's real 2026-08-26 grid has exactly one row across the WHOLE
    snapshot missing a side of the smile: expiry=2027-01-15, strike=28,
    put_iv NULL. atm_iv must fall back to call_iv alone, basis='call_only'
    -- never interpolated from a neighboring strike. See the module
    docstring's DEVIATION note: the report_date/session pairing here is a
    constructed test date, not a live UW calendar fact -- the strike, IV,
    and spot are real."""
    _seed_grid_row(conn, "CRWV", date(2027, 1, 15), 28, 1.13983701509183, None, 92.5500)
    _seed_calendar(
        conn, {"ticker": "CRWV", "report_date": date(2026, 9, 5), "session": None}
    )

    result = implied_move_snapshot(conn, as_of=_MARKET_DATE, schema="uw_scan")
    assert result == {"prints_upcoming": 1, "covered": 1, "not_covered": 0}

    row = ImpliedMoveRepository(conn, schema="uw_scan").latest_for(["CRWV"])["CRWV"]
    assert row["iv_basis"] == "call_only"
    assert float(row["atm_iv"]) == pytest.approx(1.13983701509183)
    expected_pct, basis = _expected_move(1.13983701509183, None, 142)
    assert basis == "call_only"
    assert float(row["implied_move_pct"]) == pytest.approx(expected_pct)


def test_ticker_with_calendar_row_but_no_surface_rows_writes_nothing(conn):
    """MSFT's real upcoming print (report_date=2026-11-04, session=None) is
    seeded on the calendar, but ZERO option_surface_grid_daily rows exist
    for it in this test's schema -- the absence-of-row coverage rule: no
    zero, no interpolation, no nearest-other-date fallback. `not_covered`
    must be counted, not silently dropped."""
    _seed_calendar(
        conn, {"ticker": "MSFT", "report_date": date(2026, 11, 4), "session": None}
    )
    as_of = date(2026, 10, 20)  # within 21 days of the real 2026-11-04 report

    result = implied_move_snapshot(conn, as_of=as_of, schema="uw_scan")
    assert result == {"prints_upcoming": 1, "covered": 0, "not_covered": 1}

    assert ImpliedMoveRepository(conn, schema="uw_scan").latest_for(["MSFT"]) == {}


def test_multi_ticker_snapshot_aggregates_counters_honestly(conn):
    """Two covered prints + one uncovered in a single run -> the returned
    counters are the honest sum, not a guess. The uncovered leg is ORCL's
    real report_date=2026-09-08, report_time="unknown" (session=None) --
    deliberately given NO option_surface_grid_daily rows (ORCL is not on
    argon's watchlist-driven surface capture)."""
    _seed_avgo_grid(conn)
    _seed_adbe_grid(conn)
    _seed_calendar(
        conn,
        {"ticker": "AVGO", "report_date": date(2026, 9, 2), "session": "afterhours"},
        {"ticker": "ADBE", "report_date": date(2026, 9, 10), "session": "afterhours"},
        {"ticker": "ORCL", "report_date": date(2026, 9, 8), "session": None},
    )

    result = implied_move_snapshot(conn, as_of=_MARKET_DATE, schema="uw_scan")
    assert result == {"prints_upcoming": 3, "covered": 2, "not_covered": 1}

    latest = ImpliedMoveRepository(conn, schema="uw_scan").latest_for(
        ["AVGO", "ADBE", "ORCL"]
    )
    assert set(latest) == {"AVGO", "ADBE"}


def test_rerun_same_night_is_idempotent_new_rows_zero_on_replay(conn):
    _seed_avgo_grid(conn)
    _seed_calendar(
        conn,
        {"ticker": "AVGO", "report_date": date(2026, 9, 2), "session": "afterhours"},
    )

    implied_move_snapshot(conn, as_of=_MARKET_DATE, schema="uw_scan")
    repo = ImpliedMoveRepository(conn, schema="uw_scan")
    row = repo.latest_for(["AVGO"])["AVGO"]
    # A direct upsert_rows replay of the exact same row reports 0 genuinely new.
    replay = repo.upsert_rows(
        [
            {
                "ticker": "AVGO",
                "market_date": row["market_date"],
                "report_date": row["report_date"],
                "expiry": row["expiry"],
                "strike": row["strike"],
                "atm_iv": row["atm_iv"],
                "iv_basis": row["iv_basis"],
                "spot": row["spot"],
                "implied_move_pct": row["implied_move_pct"],
                "implied_move_usd": row["implied_move_usd"],
            }
        ]
    )
    assert replay == 0


def test_history_returns_every_nightly_snapshot_for_one_report_date_oldest_first(conn):
    """Two consecutive nights snapshotting the SAME upcoming AVGO print ->
    `history` returns both rows, oldest market_date first -- the delta-rail
    path into one print. AVGO's real 2026-08-26 grid values are reseeded
    verbatim under an earlier market_date (2026-08-25, for which this dev
    warm store never accrued a real snapshot) purely to exercise the
    repository's date-ordering; no new IV/strike/spot value is invented."""
    _seed_calendar(
        conn,
        {"ticker": "AVGO", "report_date": date(2026, 9, 2), "session": "afterhours"},
    )

    _seed_avgo_grid(conn, market_date=date(2026, 8, 25))
    implied_move_snapshot(conn, as_of=date(2026, 8, 25), schema="uw_scan")

    _seed_avgo_grid(conn, market_date=date(2026, 8, 26))
    implied_move_snapshot(conn, as_of=date(2026, 8, 26), schema="uw_scan")

    history = ImpliedMoveRepository(conn, schema="uw_scan").history(
        "AVGO", date(2026, 9, 2)
    )
    assert [h["market_date"] for h in history] == [date(2026, 8, 25), date(2026, 8, 26)]


def test_reaction_day_premarket_is_report_date_itself():
    from uw_scan.worker.jobs.implied_move_snapshot import _reaction_day

    assert _reaction_day(date(2026, 10, 1), "premarket") == date(2026, 10, 1)


def test_reaction_day_afterhours_is_report_date_plus_one():
    from uw_scan.worker.jobs.implied_move_snapshot import _reaction_day

    assert _reaction_day(date(2026, 9, 10), "afterhours") == date(2026, 9, 11)


def test_reaction_day_null_session_is_report_date_plus_one():
    from uw_scan.worker.jobs.implied_move_snapshot import _reaction_day

    assert _reaction_day(date(2026, 10, 29), None) == date(2026, 10, 30)
