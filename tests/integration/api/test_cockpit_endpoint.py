from __future__ import annotations

from datetime import date

from uw_scan.models import MatrixState


def test_cockpit_state_latest_returns_state_and_freshness(
    client, seeded_db_empty_cards
) -> None:
    _seed_state(seeded_db_empty_cards)

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


def test_cockpit_phase4_tabs_return_read_models(client, seeded_db_empty_cards) -> None:
    _seed_state(seeded_db_empty_cards)

    dealer = client.get("/api/cockpit/SPY/dealer")
    surface = client.get("/api/cockpit/SPY/surface")
    flow_im = client.get("/api/cockpit/SPY/flow-im")
    vrp = client.get("/api/cockpit/SPY/vrp")

    assert dealer.status_code == 200
    assert dealer.json()["points"] == []
    assert surface.status_code == 200
    assert set(surface.json()) == {"ticker", "market_date", "skew", "term"}
    assert flow_im.status_code == 200
    assert set(flow_im.json()) == {
        "ticker",
        "market_date",
        "alerts",
        "implied_moves",
    }
    assert vrp.status_code == 200
    assert set(vrp.json()) == {"ticker", "market_date", "points"}


def test_cockpit_state_rejects_ticker_outside_universe(client, seeded_db_empty_cards):
    r = client.get("/api/cockpit/TSLA/state")

    assert r.status_code == 404
    assert "not in Cockpit universe" in r.json()["detail"]


def test_cockpit_state_missing_asof_returns_404(client, seeded_db_empty_cards):
    r = client.get("/api/cockpit/SPY/state?asof=2026-05-15")

    assert r.status_code == 404
    assert "no Cockpit state" in r.json()["detail"]


def _seed_state(repo) -> None:
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
