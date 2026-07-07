from __future__ import annotations

from datetime import date, timedelta

from uw_scan.reports.data_freshness import FreshnessRow
from uw_scan.storage.data_freshness_repository import DataFreshnessRepository


def _night(n: int) -> date:
    """N calendar days before today. `consecutive_frozen_counts` filters on
    `run_date > CURRENT_DATE - lookback`, so these tests MUST anchor their
    snapshot dates to today — hardcoded absolute dates silently drift out of
    the lookback window as the calendar advances and the streak miscounts."""
    return date.today() - timedelta(days=n)


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


def _row(table_name: str, frozen: bool) -> FreshnessRow:
    return FreshnessRow(
        table_name,
        "market_date",
        "watchlist",
        100,
        0,
        0.0,
        date(2026, 6, 1),
        30,
        frozen,
    )


def test_consecutive_frozen_counts_stops_at_first_healthy_night(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    fr = DataFreshnessRepository(repo.conn, schema=repo._schema)
    # frozen, frozen, frozen, HEALTHY, frozen (oldest) -- streak from today
    # backward must stop at the healthy night, not count the older frozen one.
    fr.upsert_snapshot(_night(1), [_row("vrp_daily", True)])
    fr.upsert_snapshot(_night(2), [_row("vrp_daily", True)])
    fr.upsert_snapshot(_night(3), [_row("vrp_daily", True)])
    fr.upsert_snapshot(_night(4), [_row("vrp_daily", False)])
    fr.upsert_snapshot(_night(5), [_row("vrp_daily", True)])
    counts = fr.consecutive_frozen_counts(lookback=14)
    assert counts["vrp_daily"] == 3


def test_consecutive_frozen_counts_zero_when_most_recent_night_healthy(
    seeded_db_empty_cards,
):
    repo = seeded_db_empty_cards
    fr = DataFreshnessRepository(repo.conn, schema=repo._schema)
    fr.upsert_snapshot(_night(1), [_row("daily_ohlc", False)])
    fr.upsert_snapshot(_night(2), [_row("daily_ohlc", True)])
    counts = fr.consecutive_frozen_counts(lookback=14)
    assert counts["daily_ohlc"] == 0


def test_consecutive_frozen_counts_stops_at_a_missing_monitor_night(
    seeded_db_empty_cards,
):
    repo = seeded_db_empty_cards
    fr = DataFreshnessRepository(repo.conn, schema=repo._schema)
    # frozen, frozen, [monitor didn't run on night 3], frozen (older) -- the gap
    # means the state through night 3 is unknown, not confirmed frozen, so the
    # streak must stop there rather than bridging across the missing night.
    fr.upsert_snapshot(_night(1), [_row("vrp_daily", True)])
    fr.upsert_snapshot(_night(2), [_row("vrp_daily", True)])
    fr.upsert_snapshot(_night(4), [_row("vrp_daily", True)])
    counts = fr.consecutive_frozen_counts(lookback=14)
    assert counts["vrp_daily"] == 2


def test_latest_snapshot_includes_consecutive_frozen_nights(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    fr = DataFreshnessRepository(repo.conn, schema=repo._schema)
    fr.upsert_snapshot(_night(2), [_row("wgc_etf_monthly", True)])
    fr.upsert_snapshot(_night(1), [_row("wgc_etf_monthly", True)])
    latest = fr.latest_snapshot()
    assert latest[0]["consecutive_frozen_nights"] == 2
