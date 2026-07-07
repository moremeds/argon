"""/positions — VRP-macro trade-lifecycle read-back (#223).

Lists captured cohorts as a portfolio with entry credit / P&L / expiry status,
and serves a per-cohort P&L curve. Read-only; no UW/IB calls.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from fastapi.testclient import TestClient


def _seed(repo, *, birth_date, expiry, origin="auto"):
    eid = repo.insert_vrp_macro_entry(
        name="SPX",
        birth_date=birth_date,
        born_at=datetime.now(timezone.utc),
        origin=origin,
        expiry=expiry,
        hold_days=30,
        spot_at_birth=6000,
        iv_at_birth=0.16,
        vrp_z_at_birth=0.6,
        weight_at_birth=1.0,
        action_at_birth="TRADE",
        short_delta=0.25,
        wing_delta=0.125,
        short_above=5800,
        short_below=5790,
        wing_above=5600,
        wing_below=5590,
    )
    t0 = datetime(2026, 6, 24, 14, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 7, 5, 14, 0, tzinfo=timezone.utc)

    def q(as_of, leg, bid, ask, session="rth"):
        return dict(
            entry_id=eid,
            as_of=as_of,
            session=session,
            leg=leg,
            strike=5800 if "short" in leg else 5600,
            opt_right="P",
            nbbo_bid=bid,
            nbbo_ask=ask,
            iv=0.17,
            delta=-0.25,
            gamma=0.001,
            vega=8.0,
            theta=-1.0,
            und_spot=6050,
            source="xenon_ib",
            greeks_source="bs",
            source_asof=None,
        )

    repo.insert_vrp_macro_entry_quotes(
        [q(t0, "short_above", 12.0, 12.4), q(t0, "wing_above", 4.0, 4.4)]
    )
    repo.insert_vrp_macro_entry_quotes(
        [
            q(t1, "short_above", 5.8, 6.2, "eod"),
            q(t1, "wing_above", 1.8, 2.2, "eod"),
        ]
    )
    repo.conn.commit()
    return eid


def test_list_positions_portfolio(client: TestClient, seeded_db_empty_cards):
    today = date.today()
    eid = _seed(
        seeded_db_empty_cards,
        birth_date=today - timedelta(days=5),
        expiry=today + timedelta(days=30),
    )
    res = client.get("/api/positions")
    assert res.status_code == 200
    body = res.json()
    assert body["open_count"] == 1
    p = next(p for p in body["positions"] if p["entry_id"] == eid)
    assert p["status"] == "open"
    # credit 8.0, current value 4.0 -> pnl 4.0
    assert float(p["entry_credit"]) == 8.0
    assert float(p["unrealized_pnl"]) == 4.0
    assert p["n_marks"] == 2
    assert float(body["total_unrealized_pnl"]) == 4.0


def test_position_detail_pnl_series(client: TestClient, seeded_db_empty_cards):
    today = date.today()
    eid = _seed(
        seeded_db_empty_cards,
        birth_date=today - timedelta(days=5),
        expiry=today + timedelta(days=30),
    )
    res = client.get(f"/api/positions/{eid}")
    assert res.status_code == 200
    body = res.json()
    assert body["position"]["entry_id"] == eid
    assert len(body["pnl_series"]) == 2
    assert float(body["pnl_series"][0]["unrealized_pnl"]) == 0.0
    assert float(body["pnl_series"][1]["unrealized_pnl"]) == 4.0


def test_position_detail_404(client: TestClient, seeded_db_empty_cards):
    res = client.get("/api/positions/999999")
    assert res.status_code == 404
