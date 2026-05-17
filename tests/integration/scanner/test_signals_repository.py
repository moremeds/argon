"""Integration tests for SignalsRepository."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from uw_scan.storage.repository import Repository
from uw_scan.storage.signals_repository import SignalsRepository


def test_upsert_signal_hit_idempotent(seeded_db_empty_cards):
    repo: Repository = seeded_db_empty_cards
    sigs = SignalsRepository(repo.conn, schema="uw_scan")
    # The fixture's seed includes a watchlist; pick any seeded ticker
    # (AAPL is in the standard 54-ticker seed).
    run_id = repo.insert_scan_run("AAPL", notes="signals test")

    sigs.upsert_signal_hit(
        run_id=run_id,
        ticker="AAPL",
        signal_type="deep_conviction_flow",
        tier=1,
        score=Decimal("0.85"),
        evidence={"qualifying_alerts": 3, "total_premium": "1500000"},
        freshness="live",
    )
    sigs.upsert_signal_hit(
        run_id=run_id,
        ticker="AAPL",
        signal_type="deep_conviction_flow",
        tier=1,
        score=Decimal("0.90"),
        evidence={"qualifying_alerts": 4, "total_premium": "1800000"},
        freshness="live",
    )
    repo.conn.commit()

    hits = sigs.fetch_hits_for_run(run_id, "AAPL")
    assert len(hits) == 1
    assert hits[0]["score"] == Decimal("0.900")
    assert hits[0]["evidence"]["qualifying_alerts"] == 4


def test_upsert_context_flag_and_gate(seeded_db_empty_cards):
    repo: Repository = seeded_db_empty_cards
    sigs = SignalsRepository(repo.conn, schema="uw_scan")
    run_id = repo.insert_scan_run("TSLA", notes="signals test")

    sigs.upsert_context_flag(
        run_id=run_id,
        ticker="TSLA",
        layer="pcr_sentiment",
        label="Extreme Fear",
        value=Decimal("1.7500"),
    )
    sigs.upsert_gate(
        run_id=run_id,
        ticker="TSLA",
        earnings="pass",
        liquidity="block",
        regime="pass",
    )
    repo.conn.commit()

    flags = sigs.fetch_context_flags_for_run(run_id, "TSLA")
    assert flags == [
        {"layer": "pcr_sentiment", "label": "Extreme Fear", "value": Decimal("1.7500")}
    ]
    gate = sigs.fetch_gate_for_run(run_id, "TSLA")
    assert gate == {"earnings": "pass", "liquidity": "block", "regime": "pass"}


def test_fetch_dark_pool_window_filters_age_and_canceled(seeded_db_empty_cards):
    repo: Repository = seeded_db_empty_cards
    sigs = SignalsRepository(repo.conn, schema="uw_scan")
    run_id = repo.insert_scan_run("AAPL", notes="dp window test")

    now = datetime.now(timezone.utc)
    rows = [
        # Inside window, valid
        (
            "AAPL",
            1,
            now - timedelta(days=1),
            Decimal("185.00"),
            5000,
            Decimal("925000"),
            False,
        ),
        # Inside window, canceled — must be filtered
        (
            "AAPL",
            2,
            now - timedelta(days=2),
            Decimal("185.10"),
            5000,
            Decimal("925500"),
            True,
        ),
        # Outside 5-day window — must be filtered
        (
            "AAPL",
            3,
            now - timedelta(days=10),
            Decimal("180.00"),
            5000,
            Decimal("900000"),
            False,
        ),
        # Inside window, NULL premium — must be filtered
        ("AAPL", 4, now - timedelta(hours=2), Decimal("186.00"), 5000, None, False),
    ]
    with repo.conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO uw_scan.dark_pool_events
               (run_id, ticker, tracking_id, executed_at, price, size,
                premium, canceled)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            [(run_id, *r) for r in rows],
        )
    repo.conn.commit()

    prints = sigs.fetch_dark_pool_window("AAPL", lookback_days=5)
    assert len(prints) == 1
    assert prints[0]["tracking_id"] == 1
    assert prints[0]["premium"] == Decimal("925000")
