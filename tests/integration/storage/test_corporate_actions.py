from __future__ import annotations

from datetime import date
from decimal import Decimal


def test_corporate_action_roundtrip(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    repo.upsert_corporate_action(
        ticker="NVDA",
        event_type="split",
        event_date=date(2024, 6, 10),
        split_ratio=Decimal("10"),
    )
    repo.upsert_corporate_action(
        ticker="NVDA",
        event_type="dividend",
        event_date=date(2024, 9, 12),
        cash_amount=Decimal("0.01"),
    )
    repo.conn.commit()
    rows = repo.fetch_corporate_actions("NVDA")
    assert [r["event_type"] for r in rows] == ["split", "dividend"]
    assert rows[0]["split_ratio"] == Decimal("10")
    assert rows[1]["cash_amount"] == Decimal("0.01")


def test_corporate_action_upsert_is_idempotent(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    for ratio in ("4", "10"):
        repo.upsert_corporate_action(
            ticker="NVDA",
            event_type="split",
            event_date=date(2024, 6, 10),
            split_ratio=Decimal(ratio),
        )
    repo.conn.commit()
    rows = repo.fetch_corporate_actions("NVDA")
    assert len(rows) == 1  # same PK → updated, not duplicated
    assert rows[0]["split_ratio"] == Decimal("10")


def test_fetch_distinct_vrp_tickers(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    with repo.conn.cursor() as cur:
        for tk in ("AAPL", "AAPL", "MSFT"):
            cur.execute(
                f"INSERT INTO {repo._schema}.vrp_daily "
                "(ticker, market_date, iv, rv, vrp, vrp_z_20) "
                "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                (
                    tk,
                    date(2026, 1, 5) if tk == "AAPL" else date(2026, 1, 6),
                    0.3,
                    0.2,
                    0.1,
                    1.2,
                ),
            )
    repo.conn.commit()
    assert repo.fetch_distinct_vrp_tickers() == ["AAPL", "MSFT"]
