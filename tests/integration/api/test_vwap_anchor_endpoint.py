from datetime import date

import pytest

from uw_scan.storage.technicals_repository import TechnicalsRepository


def _seed(repo):
    trepo = TechnicalsRepository(repo.conn)
    trepo.upsert_series(
        "NVDA",
        [
            {
                "as_of": date(2026, 7, 6),
                "open": 9.0,
                "high": 10.0,
                "low": 8.0,
                "close": 9.0,
                "volume": 100,
            },
            {
                "as_of": date(2026, 7, 7),
                "open": 10.5,
                "high": 12.0,
                "low": 10.0,
                "close": 11.0,
                "volume": 300,
            },
        ],
    )


def test_post_computes_persists_and_get_returns(client, seeded_db_empty_cards):
    _seed(seeded_db_empty_cards)
    resp = client.post(
        "/api/stock/NVDA/vwap-anchor", json={"anchor_date": "2026-07-06"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["anchor_date"] == "2026-07-06"
    assert [p["as_of"] for p in body["series"]] == ["2026-07-06", "2026-07-07"]
    assert body["series"][0]["vwap"] == pytest.approx(9.0)
    assert body["series"][1]["vwap"] == pytest.approx(10.5)

    # technicals GET now carries OHLCV per row and the persisted anchor
    got = client.get("/api/stock/NVDA/technicals").json()
    assert got["series"][0]["open"] == 9.0
    assert got["series"][0]["volume"] == 100
    assert got["vwap_anchor"]["anchor_date"] == "2026-07-06"
    assert len(got["vwap_anchor"]["series"]) == 2


def test_post_rejects_non_bar_anchor(client, seeded_db_empty_cards):
    _seed(seeded_db_empty_cards)
    resp = client.post(
        "/api/stock/NVDA/vwap-anchor", json={"anchor_date": "2026-07-05"}
    )
    assert resp.status_code == 400


def test_delete_clears_anchor(client, seeded_db_empty_cards):
    _seed(seeded_db_empty_cards)
    client.post("/api/stock/NVDA/vwap-anchor", json={"anchor_date": "2026-07-06"})
    assert client.delete("/api/stock/NVDA/vwap-anchor").status_code == 204
    assert client.get("/api/stock/NVDA/technicals").json()["vwap_anchor"] is None
    assert client.delete("/api/stock/NVDA/vwap-anchor").status_code == 204  # idempotent


def test_vwap_model_exports():
    from uw_scan.models import (  # noqa: F401
        TechnicalsVwapAnchor,
        VwapAnchorRequest,
        VwapPoint,
    )

    assert TechnicalsVwapAnchor.__module__ == "uw_scan.models"
