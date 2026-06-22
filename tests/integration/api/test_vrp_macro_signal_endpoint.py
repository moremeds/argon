from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient


def _seed_spx_skip(repo) -> None:
    # Real frozen SPX readout (observed 2026-06-22): vol cheap → ramp+ → SKIP.
    repo.upsert_vrp_macro_signal(
        name="SPX",
        snapshot_date=date(2026, 6, 22),
        as_of=date(2026, 5, 21),
        spot=7445.72,
        iv=0.164,
        rv20=0.1612,
        vrp=0.0028,
        vrp_z=-1.953,
        weight=0.0,
        action="SKIP",
        short_put=None,
        long_put=None,
        put_width=None,
        credit=None,
        max_loss=None,
        hold_days=30,
        short_delta=0.25,
        wing_delta=0.125,
        bt_n=522,
        bt_sharpe=1.6524,
        bt_maxdd=-0.796,
        bt_annror=0.53,
        bt_calmar=0.67,
        config={"sizing": "ramp+"},
    )
    repo.conn.commit()


def test_vrp_macro_signal_endpoint_returns_seeded_row(
    client: TestClient, seeded_db_empty_cards
) -> None:
    _seed_spx_skip(seeded_db_empty_cards)

    res = client.get("/api/regime/vrp-macro-signal")
    assert res.status_code == 200
    body = res.json()
    assert "signals" in body
    assert len(body["signals"]) == 1
    s = body["signals"][0]
    assert s["name"] == "SPX"
    assert s["action"] == "SKIP"
    assert s["weight"] == 0.0
    assert s["as_of"] == "2026-05-21"
    assert s["snapshot_date"] == "2026-06-22"
    assert s["bt_sharpe"] == 1.6524
    assert s["short_put"] is None  # SKIP → no modeled structure


def test_vrp_macro_signal_endpoint_empty_is_ok(
    client: TestClient, seeded_db_empty_cards
) -> None:
    res = client.get("/api/regime/vrp-macro-signal")
    assert res.status_code == 200
    assert res.json() == {"signals": []}
