from __future__ import annotations

from datetime import date

import pytest

from uw_scan.reports.data_freshness import MonitoredTable, compute_freshness


def _seed_greek_daily(repo, ticker, trade_date):
    from uw_scan.storage.greek_exposure_repository import GreekExposureDailyRepository

    g = GreekExposureDailyRepository(repo.conn, schema=repo._schema)
    g.upsert_rows(
        ticker,
        [
            {
                "trade_date": trade_date,
                "call_gex": 1.0,
                "put_gex": -1.0,
                "call_delta": 1.0,
                "put_delta": -1.0,
                "payload": {},
            }
        ],
    )


def test_frozen_table_flagged(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    today = date(2026, 6, 25)
    # Newest data is 5 weeks old -> frozen.
    _seed_greek_daily(repo, "NVDA", date(2026, 5, 20))
    monitored = [
        MonitoredTable(
            name="greek_exposure_daily", scope="watchlist", expected_tickers=None
        )
    ]
    rows = compute_freshness(
        repo.conn, repo._schema, monitored, active_tickers=["NVDA", "AMD"], today=today
    )
    assert len(rows) == 1
    r = rows[0]
    assert r.date_col == "trade_date"
    assert r.max_data_date == date(2026, 5, 20)
    assert r.days_stale == (today - date(2026, 5, 20)).days
    assert r.frozen is True


def test_fresh_table_not_frozen(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    today = date(2026, 6, 25)
    _seed_greek_daily(repo, "NVDA", date(2026, 6, 24))  # yesterday
    monitored = [
        MonitoredTable(
            name="greek_exposure_daily", scope="watchlist", expected_tickers=None
        )
    ]
    rows = compute_freshness(
        repo.conn, repo._schema, monitored, active_tickers=["NVDA"], today=today
    )
    assert rows[0].frozen is False
    assert rows[0].coverage_pct == pytest.approx(1.0)


def test_subset_scope_uses_named_denominator(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    today = date(2026, 6, 25)
    _seed_greek_daily(repo, "SPY", date(2026, 6, 24))
    monitored = [
        MonitoredTable(
            name="greek_exposure_daily",
            scope="subset",
            expected_tickers=frozenset({"SPX", "SPY", "TLT"}),
        )
    ]
    rows = compute_freshness(
        repo.conn, repo._schema, monitored, active_tickers=["AAPL"], today=today
    )
    # Coverage measured vs the 3-name subset, not the 1-name active list.
    assert rows[0].expected_count == 3
    assert rows[0].covered_count == 1
    assert rows[0].coverage_pct == pytest.approx(1 / 3)


def test_ticker_less_table_is_freshness_only(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    today = date(2026, 6, 25)
    # option_intraday_buckets has no ticker/underlying column (only
    # option_symbol). The monitor must still compute data-date freshness, with
    # coverage fields null.
    with repo.conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {repo._schema}.option_intraday_buckets
                (option_symbol, trade_date, start_time, close)
            VALUES ('TSLA260710C00410000', %s, %s, 1.0)
            """,
            (date(2026, 5, 20), "2026-05-20T14:30:00+00:00"),
        )
    repo.conn.commit()
    monitored = [
        MonitoredTable(
            name="option_intraday_buckets", scope="watchlist", expected_tickers=None
        )
    ]
    rows = compute_freshness(
        repo.conn, repo._schema, monitored, active_tickers=["TSLA"], today=today
    )
    r = rows[0]
    assert r.date_col == "trade_date"
    assert r.max_data_date == date(2026, 5, 20)
    assert r.frozen is True  # 5-weeks stale -> frozen flagged
    assert r.coverage_pct is None  # no ticker column -> no coverage
    assert r.expected_count == 0
