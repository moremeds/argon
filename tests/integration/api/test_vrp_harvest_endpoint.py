from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient


def test_vrp_harvest_endpoint_returns_seeded_verdicts(
    client: TestClient, seeded_db_empty_cards
) -> None:
    repo = seeded_db_empty_cards
    repo.upsert_vrp_harvest_verdict(
        asset_class="single_name",
        deviation_class="RICH",
        verdict="HARVEST_SELLABLE",
        mean_realized_vrp=0.031,
        mean_holdout=0.028,
        rich_cheap_spread=0.015,
        n=42,
        n_holdout=17,
        survives_walkforward=True,
        survives_window_gate=True,
        confidence="med",
        as_of=date(2026, 6, 21),
    )
    repo.conn.commit()

    res = client.get("/api/regime/vrp-harvest")
    assert res.status_code == 200
    body = res.json()
    assert "verdicts" in body
    assert len(body["verdicts"]) == 1
    v = body["verdicts"][0]
    assert v["asset_class"] == "single_name"
    assert v["deviation_class"] == "RICH"
    assert v["verdict"] == "HARVEST_SELLABLE"
    assert v["mean_realized_vrp"] == 0.031
    assert v["n"] == 42


def test_vrp_harvest_endpoint_empty_is_ok(client: TestClient, seeded_db_empty_cards):
    res = client.get("/api/regime/vrp-harvest")
    assert res.status_code == 200
    assert res.json() == {"verdicts": []}
