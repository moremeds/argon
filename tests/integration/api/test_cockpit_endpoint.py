from __future__ import annotations

from datetime import date

from uw_scan.models import MatrixState


def test_cockpit_state_latest_returns_state_and_freshness(
    client, seeded_db_empty_cards
) -> None:
    repo = seeded_db_empty_cards
    repo.upsert_matrix_state_snapshot(
        MatrixState(
            ticker="SPY",
            market_date=date(2026, 5, 15),
            vanna_state="stale",
            charm_state="stale",
            skew_state="neutral",
            term_state="vol_down",
            im_state="stale",
            flow_state="stale",
            vrp_state="neutral",
            consistency_tier="insufficient_data",
            cluster_coverage_ok=False,
            term_classification="contango",
        )
    )
    repo.conn.commit()

    r = client.get("/api/cockpit/SPY/state")

    assert r.status_code == 200
    body = r.json()
    assert body["state"]["ticker"] == "SPY"
    assert body["state"]["market_date"] == "2026-05-15"
    assert body["state"]["consistency_tier"] == "insufficient_data"
    assert set(body["freshness"]) == {
        "vanna_charm",
        "skew",
        "term",
        "im_vrp",
        "vrp_rv",
        "oi",
    }


def test_cockpit_state_rejects_ticker_outside_universe(client, seeded_db_empty_cards):
    r = client.get("/api/cockpit/TSLA/state")

    assert r.status_code == 404
    assert "not in Cockpit universe" in r.json()["detail"]


def test_cockpit_state_missing_asof_returns_404(client, seeded_db_empty_cards):
    r = client.get("/api/cockpit/SPY/state?asof=2026-05-15")

    assert r.status_code == 404
    assert "no Cockpit state" in r.json()["detail"]
