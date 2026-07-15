from __future__ import annotations

from datetime import date

from uw_scan.storage.chanlun_signal_repository import ChanlunSignalRepository


def test_lifecycle_endpoint_returns_current_states_excluding_stale(
    client, seeded_db_empty_cards
):
    repo = seeded_db_empty_cards
    r = ChanlunSignalRepository(repo.conn, schema=repo._schema)
    r.upsert_transition(
        ticker="AAPL",
        category="vertex",
        kind="bottom",
        extreme_date=date(2026, 7, 1),
        extreme_price=195.5,
        state="pending",
        reason=None,
        as_of=date(2026, 7, 1),
        details={},
    )
    # A breach-invalidated mark IS returned (spec §API keeps non-stale terminals).
    r.upsert_transition(
        ticker="AAPL",
        category="divergence",
        kind="bottom",
        extreme_date=date(2026, 6, 1),
        extreme_price=180.0,
        state="invalidated",
        reason="breach",
        as_of=date(2026, 6, 10),
        details={},
    )
    # A stale-invalidated mark must be EXCLUDED from the response (spec §API).
    r.upsert_transition(
        ticker="AAPL",
        category="vertex",
        kind="top",
        extreme_date=date(2026, 5, 1),
        extreme_price=210.0,
        state="pending",
        reason=None,
        as_of=date(2026, 5, 1),
        details={},
    )
    r.upsert_transition(
        ticker="AAPL",
        category="vertex",
        kind="top",
        extreme_date=date(2026, 5, 1),
        extreme_price=210.0,
        state="invalidated",
        reason="stale",
        as_of=date(2026, 6, 1),
        details={},
    )
    resp = client.get("/api/stock/aapl/chanlun/lifecycle")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ticker"] == "AAPL"
    assert len(body["marks"]) == 2  # non-vacuity: pending + breach, stale gone
    states = {(m["category"], m["state"], m["reason"]) for m in body["marks"]}
    assert ("vertex", "pending", None) in states
    assert ("divergence", "invalidated", "breach") in states
    assert all(m["reason"] != "stale" for m in body["marks"])


def test_lifecycle_endpoint_empty_ticker_is_empty_list(client, seeded_db_empty_cards):
    resp = client.get("/api/stock/ZZZ/chanlun/lifecycle")
    assert resp.status_code == 200
    assert resp.json() == {"ticker": "ZZZ", "marks": []}
