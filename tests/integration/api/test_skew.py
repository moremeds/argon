"""Integration test: GET /api/stock/{ticker}/skew."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def repo(seeded_db_empty_cards):
    """Alias for the canonical bare-Repository fixture; same test DB the client reads."""
    return seeded_db_empty_cards


def _seed_rr_rv(repo, ticker="AAPL", n=210):
    base = date(2026, 1, 1)
    with repo.conn.cursor() as cur:
        for i in range(n):
            d = base + timedelta(days=i)
            cur.execute(
                "INSERT INTO uw_scan.risk_reversal_skew_history "
                "(ticker, market_date, delta, expiry, risk_reversal) "
                "VALUES (%s,%s,25,%s,%s) ON CONFLICT DO NOTHING",
                (ticker, d, base + timedelta(days=300), 0.001 if i < n - 1 else 0.05),
            )
            cur.execute(
                "INSERT INTO uw_scan.realized_volatility_history "
                "(ticker, market_date, price, implied_volatility, realized_volatility) "
                "VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (ticker, d, 100 - i * 0.05, 0.2 + i * 0.0005, 0.18),
            )
            cur.execute(
                "INSERT INTO uw_scan.realized_volatility_history "
                "(ticker, market_date, price, implied_volatility, realized_volatility) "
                "VALUES ('SPY',%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (d, 400 + (i % 3), 0.15, 0.14),
            )
    repo.conn.commit()


def test_skew_endpoint_shape(client: TestClient, repo):
    _seed_rr_rv(repo, "AAPL")
    r = client.get("/api/stock/AAPL/skew")
    assert r.status_code == 200
    body = r.json()
    assert body["ticker"] == "AAPL"
    assert body["deviation_class"] in {"RICH", "CHEAP", "NORMAL"}
    assert body["directional_lean"] in {"BULLISH_TILT", "BEARISH_TILT", "NEUTRAL"}
    assert "directional_lean" in body["read"]
    assert isinstance(body["history"], list)


def test_skew_endpoint_empty_ticker(client: TestClient, repo):
    r = client.get("/api/stock/ZZZZ/skew")
    assert r.status_code == 200
    assert r.json()["backfill_status"] == "empty"


def test_skew_endpoint_surfaces_seeded_verdict(client: TestClient, repo):
    """Spec §9 'assembler wiring': a TRADABLE_* verdict for the computed bucket
    surfaces as a non-neutral lean; absent verdict => NEUTRAL."""
    _seed_rr_rv(repo, "AAPL")
    first = client.get("/api/stock/AAPL/skew").json()
    assert first["directional_lean"] == "NEUTRAL"  # no verdict yet
    # seed a TRADABLE_BEAR verdict for the EXACT bucket the response reports
    repo.upsert_skew_directional_verdict(
        asset_class=first["asset_class"],
        deviation_class=first["deviation_class"],
        drive_class=first["read"]["drive"] or first["drive_class"],
        regime=first["regime"],
        verdict="TRADABLE_BEAR",
        confidence="med",
        forward_sep=Decimal("-0.02"),
        n=40,
        borrow_clean=True,
        survives_gate=True,
        as_of=date(2026, 6, 1),
    )
    repo.conn.commit()
    second = client.get("/api/stock/AAPL/skew").json()
    # lean is non-neutral only if the live borrow/earnings gates also pass;
    # the AAPL seed is normal-borrow + no earnings row => gates pass.
    assert second["directional_lean"] in {"BEARISH_TILT", "NEUTRAL"}
    if second["borrow_flag"] != "hard_to_borrow" and second["earnings_gate"] != "block":
        assert second["directional_lean"] == "BEARISH_TILT"
        assert second["read"]["directional_lean"]["express"]
