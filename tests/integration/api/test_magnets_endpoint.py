import pytest


def test_magnets_endpoint_returns_levels_from_the_real_swing(
    client, seeded_db_with_aapl_magnets
):
    r = client.get("/api/stock/AAPL/magnets")
    assert r.status_code == 200
    body = r.json()
    assert body["ticker"] == "AAPL"
    assert body["as_of"] == "2026-08-07"
    lv = body["levels"]
    assert lv["resistance"] == pytest.approx(340.08)
    assert lv["support"] == pytest.approx(275.15)
    assert lv["stretch"] == pytest.approx(340.08 + 0.618 * (340.08 - 275.15))


def test_magnets_endpoint_returns_bands_with_measured_confidence(
    client, seeded_db_with_aapl_magnets
):
    body = client.get("/api/stock/AAPL/magnets").json()
    assert body["bands"], "grid session seeded but no cone produced"
    assert {b["horizon"] for b in body["bands"]} == {5, 10, 21}
    for b in body["bands"]:
        assert b["band_sigma"] in (1.0, 1.96)
        assert 0.5 < b["measured_confidence"] < 1.0
        assert b["lower"] < b["upper"]


def test_magnets_endpoint_returns_pivots_for_the_zigzag(
    client, seeded_db_with_aapl_magnets
):
    pivots = client.get("/api/stock/AAPL/magnets").json()["pivots"]
    assert len(pivots) >= 2
    assert pivots[-1]["kind"] == "top"
    assert {p["kind"] for p in pivots} <= {"top", "bottom"}


def test_magnets_endpoint_read_never_promises_a_target(
    client, seeded_db_with_aapl_magnets
):
    joined = " ".join(client.get("/api/stock/AAPL/magnets").json()["read"]).lower()
    assert "target" not in joined
    assert "no measured edge" in joined


def test_magnets_endpoint_404s_without_price_history(client, seeded_db_empty_cards):
    assert client.get("/api/stock/NOSUCHTICKER/magnets").status_code == 404


def test_magnets_endpoint_returns_200_with_no_surface(client, seeded_db_with_ohlc):
    # AAPL has bars but no grid session: levels may be None and bands empty, and
    # that is a 200 with an honest empty payload, not an error.
    r = client.get("/api/stock/AAPL/magnets")
    assert r.status_code == 200
    assert r.json()["bands"] == []
