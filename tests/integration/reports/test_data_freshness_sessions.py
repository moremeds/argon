"""A partial heal must not read as full coverage (E2).

Measured 2026-08-16 on the mini: risk_reversal_skew_history reported
coverage_pct=1.0000 / frozen=False while Aug 11-14 each held 2 of 170 tickers.
Two real rows on the newest date drag max_data_date forward, and the 4-day
grace window then reaches back over the hole to the last healthy session.
"""

from __future__ import annotations

from datetime import date

from uw_scan.reports.data_freshness import MonitoredTable, compute_freshness

SESSIONS = [date(2026, 8, 10), date(2026, 8, 11), date(2026, 8, 12), date(2026, 8, 13)]
TICKERS = [f"T{i:03d}" for i in range(20)]


def _seed_spine(repo) -> None:
    with repo.conn.cursor() as cur:
        for d in SESSIONS:
            cur.execute(
                f"INSERT INTO {repo._schema}.daily_ohlc (ticker, date, close, source) "
                "VALUES ('SPY', %s, 100, 'massive') ON CONFLICT DO NOTHING",
                (d,),
            )
        repo.conn.commit()


def _seed_skew(repo, rows: list[tuple[date, str]]) -> None:
    with repo.conn.cursor() as cur:
        for d, t in rows:
            cur.execute(
                f"INSERT INTO {repo._schema}.risk_reversal_skew_history "
                "(ticker, market_date, delta, expiry) VALUES (%s, %s, 25, %s) "
                "ON CONFLICT DO NOTHING",
                (t, d, date(2026, 9, 18)),
            )
        repo.conn.commit()


def _run(repo):
    return compute_freshness(
        repo.conn,
        repo._schema,
        [MonitoredTable("risk_reversal_skew_history", "watchlist", None)],
        TICKERS,
        today=SESSIONS[-1],
    )


def test_partial_heal_is_reported_as_missing_sessions(seeded_db_empty_cards) -> None:
    repo = seeded_db_empty_cards
    _seed_spine(repo)
    # The production shape: full coverage on the first session, 2 tickers after.
    rows = [(SESSIONS[0], t) for t in TICKERS]
    rows += [(d, t) for d in SESSIONS[1:] for t in TICKERS[:2]]
    _seed_skew(repo, rows)

    row = _run(repo)[0]
    assert row.sessions_missing == 3, "Aug 11/12/13 each hold 2 of 20 tickers"


def test_full_coverage_reports_zero_missing_sessions(seeded_db_empty_cards) -> None:
    repo = seeded_db_empty_cards
    _seed_spine(repo)
    _seed_skew(repo, [(d, t) for d in SESSIONS for t in TICKERS])

    assert _run(repo)[0].sessions_missing == 0
