from datetime import date

import pytest
from uw_scan.storage.greek_exposure_repository import GreekExposureDailyRepository


def test_upsert_then_fetch(seeded_db_empty_cards) -> None:
    repo = GreekExposureDailyRepository(
        seeded_db_empty_cards.conn,
        schema=seeded_db_empty_cards._schema,
    )
    repo.upsert_rows(
        "SPY",
        [
            {
                "trade_date": date(2026, 5, 14),
                "call_gex": 2.1e9,
                "put_gex": -0.9e9,
                "call_delta": 7.0e7,
                "put_delta": -1.5e7,
                "payload": {"raw": "ok"},
            },
            {
                "trade_date": date(2026, 5, 15),
                "call_gex": 2.0e9,
                "put_gex": -1.0e9,
                "call_delta": 6.5e7,
                "put_delta": -1.5e7,
                "payload": {"raw": "ok"},
            },
        ],
    )
    rows = repo.fetch_history("SPY", days=10)
    assert len(rows) == 2
    # net_gex is a generated column = call_gex + put_gex
    assert rows[-1]["net_gex"] == pytest.approx(1.0e9)
    assert rows[-1]["net_dex"] == pytest.approx(5.0e7)


def test_upsert_overwrites_on_conflict(seeded_db_empty_cards) -> None:
    repo = GreekExposureDailyRepository(
        seeded_db_empty_cards.conn,
        schema=seeded_db_empty_cards._schema,
    )
    base = {
        "trade_date": date(2026, 5, 15),
        "call_gex": 1.0,
        "put_gex": -1.0,
        "call_delta": 1.0,
        "put_delta": -1.0,
        "payload": {},
    }
    repo.upsert_rows("SPY", [base])
    repo.upsert_rows("SPY", [{**base, "call_gex": 99.0}])
    rows = repo.fetch_history("SPY", days=2)
    assert rows[0]["call_gex"] == pytest.approx(99.0)
    # Generated net_gex reflects the new call_gex
    assert rows[0]["net_gex"] == pytest.approx(98.0)
