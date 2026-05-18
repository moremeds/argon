from datetime import date

import pytest
from fastapi.testclient import TestClient

from uw_scan.storage.vol_index_repository import VolIndexRepository


def test_vol_backdrop_returns_four_series(
    client: TestClient, seeded_db_empty_cards
) -> None:
    repo = VolIndexRepository(
        seeded_db_empty_cards.conn,
        schema=seeded_db_empty_cards._schema,
    )
    for sym, base in [("VIX", 18), ("VIX3M", 21), ("VVIX", 90), ("COR1M", 11)]:
        repo.upsert_rows(
            [
                {
                    "symbol": sym,
                    "trade_date": date(2026, 5, d),
                    "open": base + d * 0.1,
                    "high": base + d * 0.1,
                    "low": base + d * 0.1,
                    "close": base + d * 0.1,
                    "adj_close": base + d * 0.1,
                    "volume": 0,
                }
                for d in range(1, 16)
            ]
        )

    res = client.get("/api/regime/vol-backdrop?days=365")
    assert res.status_code == 200
    body = res.json()
    assert set(body["series"].keys()) == {"VIX", "VIX3M", "VVIX", "COR1M"}
    assert len(body["series"]["VIX"]) <= 15
    assert body["series"]["VIX"][-1]["close"] > 0
    assert "term_structure_ratio" in body


def test_vol_backdrop_term_structure_ratio(
    client: TestClient, seeded_db_empty_cards
) -> None:
    repo = VolIndexRepository(
        seeded_db_empty_cards.conn,
        schema=seeded_db_empty_cards._schema,
    )
    repo.upsert_rows(
        [
            {
                "symbol": "VIX",
                "trade_date": date(2026, 5, 15),
                "open": 20,
                "high": 20,
                "low": 20,
                "close": 20,
                "adj_close": 20,
                "volume": 0,
            },
            {
                "symbol": "VIX3M",
                "trade_date": date(2026, 5, 15),
                "open": 25,
                "high": 25,
                "low": 25,
                "close": 25,
                "adj_close": 25,
                "volume": 0,
            },
        ]
    )
    res = client.get("/api/regime/vol-backdrop?days=365")
    body = res.json()
    # 20 / 25 = 0.80, contango
    assert body["term_structure_ratio"] == pytest.approx(0.80, rel=1e-2)
    assert body["term_structure_state"] == "contango"
