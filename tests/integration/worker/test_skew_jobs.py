"""Integration test: nightly_skew_analytics_rollup + skew_analytics_backfill."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from uw_scan.worker.jobs.skew_analytics import (
    nightly_skew_analytics_rollup,
    skew_analytics_backfill,
)


@pytest.fixture
def repo(seeded_db_empty_cards):
    return seeded_db_empty_cards


def _seed(repo, ticker, n=210):
    base = date(2026, 1, 1)
    with repo.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO uw_scan.watchlist (ticker, sector) VALUES (%s,'Tech') "
            "ON CONFLICT (ticker) DO NOTHING",
            (ticker,),
        )
        for i in range(n):
            d = base + timedelta(days=i)
            cur.execute(
                "INSERT INTO uw_scan.risk_reversal_skew_history "
                "(ticker, market_date, delta, expiry, risk_reversal) "
                "VALUES (%s,%s,25,%s,%s) ON CONFLICT DO NOTHING",
                (ticker, d, base + timedelta(days=300), 0.001 if i < n - 1 else 0.05),
            )
            cur.execute(
                "INSERT INTO uw_scan.realized_volatility_history "
                "(ticker, market_date, price, implied_volatility, realized_volatility) "
                "VALUES (%s,%s,%s,%s,0.18) ON CONFLICT DO NOTHING",
                (ticker, d, 100 - i * 0.05, 0.2 + i * 0.0005),
            )
            cur.execute(
                "INSERT INTO uw_scan.realized_volatility_history "
                "(ticker, market_date, price, implied_volatility, realized_volatility) "
                "VALUES ('SPY',%s,%s,0.15,0.14) ON CONFLICT DO NOTHING",
                (d, 400 + (i % 3)),
            )
    repo.conn.commit()


def test_rollup_writes_snapshot(repo):
    _seed(repo, "AAPL")
    nightly_skew_analytics_rollup(repo=repo)
    assert repo.get_skew_analytics_latest("AAPL") is not None


def test_backfill_writes_multiple_dates(repo):
    _seed(repo, "AAPL")
    written = skew_analytics_backfill(
        repo=repo, start=date(2026, 7, 1), end=date(2026, 7, 5)
    )
    assert written >= 1
    rows = repo.fetch_skew_analytics_history("AAPL", days=4000)
    assert len(rows) >= 1
