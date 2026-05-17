from datetime import date

import pytest
from uw_scan.storage.vol_index_repository import VolIndexRepository


def test_upsert_inserts_then_updates(seeded_db_empty_cards) -> None:
    repo = VolIndexRepository(
        seeded_db_empty_cards.conn,
        schema=seeded_db_empty_cards._schema,
    )
    repo.upsert_rows(
        [
            {
                "symbol": "VIX",
                "trade_date": date(2026, 5, 15),
                "open": 18.07,
                "high": 19.27,
                "low": 17.8,
                "close": 18.43,
                "adj_close": 18.43,
                "volume": 0,
            }
        ]
    )
    repo.upsert_rows(
        [
            {
                "symbol": "VIX",
                "trade_date": date(2026, 5, 15),
                "open": 18.07,
                "high": 19.50,
                "low": 17.8,
                "close": 18.50,
                "adj_close": 18.50,
                "volume": 0,
            }
        ]
    )
    rows = repo.fetch_history("VIX", days=5)
    assert len(rows) == 1
    assert rows[0]["close"] == pytest.approx(18.50)
    assert rows[0]["high"] == pytest.approx(19.50)


def test_fetch_history_window(seeded_db_empty_cards) -> None:
    repo = VolIndexRepository(
        seeded_db_empty_cards.conn,
        schema=seeded_db_empty_cards._schema,
    )
    rows = [
        {
            "symbol": "VIX",
            "trade_date": date(2026, 5, d),
            "open": d,
            "high": d,
            "low": d,
            "close": d,
            "adj_close": d,
            "volume": 0,
        }
        for d in range(1, 16)
    ]
    repo.upsert_rows(rows)
    out = repo.fetch_history("VIX", days=7)
    assert len(out) == 7
    # Sorted ascending by trade_date
    assert out[0]["trade_date"] < out[-1]["trade_date"]


def test_fetch_history_for_missing_symbol(seeded_db_empty_cards) -> None:
    repo = VolIndexRepository(
        seeded_db_empty_cards.conn,
        schema=seeded_db_empty_cards._schema,
    )
    assert repo.fetch_history("DOESNOTEXIST", days=30) == []
