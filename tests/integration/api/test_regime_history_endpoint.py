from datetime import date

from fastapi.testclient import TestClient

from uw_scan.storage.greek_exposure_repository import GreekExposureDailyRepository
from uw_scan.storage.vol_index_repository import VolIndexRepository


def _seed_history(repo_obj) -> None:
    schema = repo_obj._schema
    conn = repo_obj.conn
    g = GreekExposureDailyRepository(conn, schema=schema)
    g.upsert_rows(
        "SPX",
        [
            {
                "trade_date": date(2026, 5, d),
                "call_gex": 2e9,
                "put_gex": -1e9,
                "call_delta": 1e7,
                "put_delta": -1e6,
                "payload": {},
            }
            for d in range(1, 16)
        ],
    )
    v = VolIndexRepository(conn, schema=schema)
    v.upsert_rows(
        [
            {
                "symbol": "SPX",
                "trade_date": date(2026, 5, d),
                "open": 7400 + d,
                "high": 7410 + d,
                "low": 7390 + d,
                "close": 7405 + d,
                "adj_close": 7405 + d,
                "volume": 0,
            }
            for d in range(1, 16)
        ]
    )


def test_gex_endpoint_returns_history_for_spx(
    client: TestClient, seeded_db_empty_cards
) -> None:
    _seed_history(seeded_db_empty_cards)
    res = client.get("/api/regime/gex?ticker=SPX")
    assert res.status_code == 200
    body = res.json()
    assert "history" in body
    assert isinstance(body["history"], list)
    assert len(body["history"]) > 0
    entry = body["history"][-1]
    for k in ("date", "net_gex", "spot"):
        assert k in entry
    # net_gex is non-null (call_gex + put_gex = 1e9 from seed)
    assert entry["net_gex"] is not None
    # spot from vol_index_daily for SPX
    assert entry["spot"] is not None
