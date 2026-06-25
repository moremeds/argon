from __future__ import annotations

from datetime import date

from uw_scan.reports.data_freshness import FreshnessRow
from uw_scan.storage.data_freshness_repository import DataFreshnessRepository


def test_upsert_and_latest(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    fr = DataFreshnessRepository(repo.conn, schema=repo._schema)
    rows = [
        FreshnessRow(
            "vrp_daily",
            "market_date",
            "watchlist",
            100,
            9,
            0.09,
            date(2026, 5, 22),
            34,
            True,
        ),
        FreshnessRow(
            "daily_ohlc",
            "market_date",
            "watchlist",
            100,
            100,
            1.0,
            date(2026, 6, 24),
            1,
            False,
        ),
    ]
    assert fr.upsert_snapshot(date(2026, 6, 25), rows) == 2
    latest = fr.latest_snapshot()
    by_name = {r["table_name"]: r for r in latest}
    assert by_name["vrp_daily"]["frozen"] is True
    assert by_name["daily_ohlc"]["frozen"] is False
    assert by_name["vrp_daily"]["coverage_pct"] == 0.09


def test_upsert_is_idempotent(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    fr = DataFreshnessRepository(repo.conn, schema=repo._schema)
    row = FreshnessRow(
        "vrp_daily",
        "market_date",
        "watchlist",
        100,
        9,
        0.09,
        date(2026, 5, 22),
        34,
        True,
    )
    fr.upsert_snapshot(date(2026, 6, 25), [row])
    # Re-running the same run_date overwrites, never duplicates (PK run_date,table).
    updated = FreshnessRow(
        "vrp_daily",
        "market_date",
        "watchlist",
        100,
        50,
        0.5,
        date(2026, 6, 24),
        1,
        False,
    )
    fr.upsert_snapshot(date(2026, 6, 25), [updated])
    latest = fr.latest_snapshot()
    assert len(latest) == 1
    assert latest[0]["frozen"] is False
    assert latest[0]["covered_count"] == 50
