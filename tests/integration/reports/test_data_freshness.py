from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

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


def _seed_etf_flow(repo, ticker, obs_date):
    repo.insert_etf_flows_daily(
        ticker=ticker,
        obs_date=obs_date,
        share_change=Decimal("0"),
        premium_change_usd=Decimal("0"),
        close=Decimal("100"),
        volume=Decimal("1"),
        as_of=datetime.now(timezone.utc),
        source="UW",
    )


def test_obs_date_column_detected(seeded_db_empty_cards):
    # etf_flows_daily uses obs_date, not one of the original _DATE_COL_PREFERENCE
    # entries -- regression guard for the timezone-bug investigation follow-up
    # that added etf_flows_daily/wgc_etf_monthly/cb_gold_reserves_monthly/
    # exchange_inventory_daily monitoring.
    repo = seeded_db_empty_cards
    today = date(2026, 7, 2)
    _seed_etf_flow(repo, "GLD", date(2026, 7, 1))
    _seed_etf_flow(repo, "GLDM", date(2026, 7, 1))
    monitored = [
        MonitoredTable("etf_flows_daily", "subset", frozenset({"GLD", "IAU", "GLDM"}))
    ]
    rows = compute_freshness(
        repo.conn, repo._schema, monitored, active_tickers=[], today=today
    )
    r = rows[0]
    assert r.date_col == "obs_date"
    assert r.max_data_date == date(2026, 7, 1)
    assert r.frozen is False
    # IAU has no row -> 2/3 covered, not a false "everything's fine" 100%.
    assert r.expected_count == 3
    assert r.covered_count == 2
    assert r.coverage_pct == pytest.approx(2 / 3)


def test_per_table_grace_days_override(seeded_db_empty_cards):
    # wgc_etf_monthly is monthly-cadence; the global 4-day default grace would
    # always flag it frozen even when healthy. grace_days=45 must be honored.
    repo = seeded_db_empty_cards
    today = date(2026, 7, 2)
    with repo.conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {repo._schema}.wgc_etf_monthly
                (ticker, obs_date, source_url, as_of, source)
            VALUES ('GLD', %s, 'file:///test.xlsx', now(), 'WGC')
            """,
            (date(2026, 5, 31),),
        )
    repo.conn.commit()
    monitored_default = [
        MonitoredTable("wgc_etf_monthly", "subset", frozenset({"GLD"}))
    ]
    monitored_relaxed = [
        MonitoredTable("wgc_etf_monthly", "subset", frozenset({"GLD"}), grace_days=45)
    ]
    default_rows = compute_freshness(
        repo.conn, repo._schema, monitored_default, active_tickers=[], today=today
    )
    relaxed_rows = compute_freshness(
        repo.conn, repo._schema, monitored_relaxed, active_tickers=[], today=today
    )
    # 32 days stale: frozen under the global 4-day default, not under grace_days=45.
    assert default_rows[0].days_stale == 32
    assert default_rows[0].frozen is True
    assert relaxed_rows[0].frozen is False


def test_data_date_column_detected(seeded_db_empty_cards):
    # gex_snapshots uses data_date -- not one of the original preference
    # entries either; regression guard for the coverage-expansion pass.
    repo = seeded_db_empty_cards
    today = date(2026, 7, 2)
    with repo.conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {repo._schema}.gex_snapshots (ticker, data_date, payload)
            VALUES ('SPX', %s, '{{}}'::jsonb)
            """,
            (date(2026, 7, 1),),
        )
    repo.conn.commit()
    monitored = [MonitoredTable("gex_snapshots", "watchlist", None)]
    rows = compute_freshness(
        repo.conn, repo._schema, monitored, active_tickers=["SPX"], today=today
    )
    r = rows[0]
    assert r.date_col == "data_date"
    assert r.max_data_date == date(2026, 7, 1)
    assert r.frozen is False


def test_date_col_override_bypasses_auto_detection(seeded_db_empty_cards):
    # rates_fiscal_debt_daily's real "as of" column is record_date, which is
    # not (and should not become) a generic _DATE_COL_PREFERENCE entry --
    # explicit date_col_override is how a one-off column name gets used.
    repo = seeded_db_empty_cards
    today = date(2026, 7, 2)
    with repo.conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {repo._schema}.rates_fiscal_debt_daily
                (record_date, as_of, total_public_debt)
            VALUES (%s, now(), 1000000)
            """,
            (date(2026, 6, 30),),
        )
    repo.conn.commit()
    monitored = [
        MonitoredTable(
            "rates_fiscal_debt_daily",
            "watchlist",
            None,
            date_col_override="record_date",
        )
    ]
    rows = compute_freshness(
        repo.conn, repo._schema, monitored, active_tickers=[], today=today
    )
    r = rows[0]
    assert r.date_col == "record_date"
    assert r.max_data_date == date(2026, 6, 30)
    assert r.days_stale == 2
