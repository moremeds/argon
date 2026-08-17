"""The spine must survive a truncated reference table (E3).

market_tide_sentiment_daily is itself CAPTURED, so an outage that stops capture
also erases the evidence of the outage. Measured 2026-08-16: the truncated spine
reported 1,276 gaps where 8,080 existed.
"""

from __future__ import annotations

from datetime import date

from uw_scan.reports.data_gap_healer import _calendar_dates, spine_health

SESSIONS = [date(2026, 8, 10), date(2026, 8, 11), date(2026, 8, 12)]


def _seed(repo, *, ref_dates, spy_dates) -> None:
    schema = repo._schema
    with repo.conn.cursor() as cur:
        for d in ref_dates:
            # state/magnitude/driver/momentum/bars are NOT NULL with no default.
            cur.execute(
                f"INSERT INTO {schema}.market_tide_sentiment_daily "
                "(data_date, state, magnitude, driver, momentum, bars) "
                "VALUES (%s, 'BALANCED', 'FLAT', 'seed', 'seed', 1) "
                "ON CONFLICT DO NOTHING",
                (d,),
            )
        for d in spy_dates:
            cur.execute(
                f"INSERT INTO {schema}.daily_ohlc "
                "(ticker, date, close, source) VALUES ('SPY', %s, 100, 'massive') "
                "ON CONFLICT DO NOTHING",
                (d,),
            )
        repo.conn.commit()


def test_spine_survives_a_truncated_reference(seeded_db_empty_cards) -> None:
    repo = seeded_db_empty_cards
    # The outage shape: the reference lost Aug 11-12, massive still has them.
    _seed(repo, ref_dates=SESSIONS[:1], spy_dates=SESSIONS)

    cal = _calendar_dates(repo.conn, repo._schema, SESSIONS[0], SESSIONS[-1])
    assert cal == SESSIONS, "witness must restore the sessions the reference lost"


def test_spine_health_names_the_missing_reference_days(seeded_db_empty_cards) -> None:
    repo = seeded_db_empty_cards
    _seed(repo, ref_dates=SESSIONS[:1], spy_dates=SESSIONS)

    health = spine_health(repo.conn, repo._schema, SESSIONS[0], SESSIONS[-1])
    assert health.ref_sessions == 1
    assert health.witness_sessions == 3
    assert health.missing_from_ref == (SESSIONS[1], SESSIONS[2])


def test_healthy_spine_reports_nothing_missing(seeded_db_empty_cards) -> None:
    repo = seeded_db_empty_cards
    _seed(repo, ref_dates=SESSIONS, spy_dates=SESSIONS)

    health = spine_health(repo.conn, repo._schema, SESSIONS[0], SESSIONS[-1])
    assert health.missing_from_ref == ()
