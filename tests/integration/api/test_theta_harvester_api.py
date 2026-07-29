"""Theta Harvester API contract."""

from __future__ import annotations

from datetime import date

import psycopg
import pytest

from uw_scan.scanners.theta_harvester import (
    DealerSupport,
    OptionLeg,
    build_candidate,
    select_short_strangle,
)
from uw_scan.storage.theta_harvester_repository import ThetaHarvesterRepository

_AS_OF = date(2026, 7, 24)
_EXP = date(2026, 8, 21)
_SPOT = 291.44


def _candidate(ticker: str, *, call_strike: float = 306.0):
    """Frozen real IWM legs, 2026-07-24 / 2026-08-21 — see Task 3 fixtures.

    LONG-convention greeks (theta <= 0, gamma >= 0) exactly as
    option_surface_grid_daily stores them; select_short_strangle negates.
    """
    put = OptionLeg(
        _EXP,
        272.0,
        "P",
        0.251489543772415,
        -0.154573982720319,
        -0.0861128240264245,
        0.0117240381034907,
        0.191878725809937,
    )
    call = OptionLeg(
        _EXP,
        call_strike,
        "C",
        0.172509740706994,
        0.156401472783266,
        -0.0595290822132382,
        0.0172246813925854,
        0.193372401778545,
    )
    structure = select_short_strangle([put, call], spot=_SPOT, as_of=_AS_OF)
    assert structure is not None
    return build_candidate(
        ticker=ticker,
        as_of=_AS_OF,
        structure=structure,
        spot=_SPOT,
        iv=0.208,
        hv20=0.1107879091536324,
        hv60=0.18596313086572983,
        trend_20d_pct=-1.8605278236543121,
        range_score=0.5346021068062862,
        dealer=DealerSupport("SUPPORT", 5.0e8, 280.0),
    )


@pytest.fixture
def seeded_candidates(client, seeded_db_empty_cards):
    """Two candidates on one session, deliberately differing in score."""
    conn = seeded_db_empty_cards.conn
    repo = ThetaHarvesterRepository(conn, "uw_scan")
    repo.upsert_candidates([_candidate("IWM"), _candidate("QQQ", call_strike=299.0)])
    conn.commit()
    return repo


def test_get_returns_empty_payload_before_any_scan(client, seeded_db_empty_cards):
    # seeded_db_empty_cards is requested for its TRUNCATE, not its rows: without
    # it this test reads whatever candidates a previously-run test left behind.
    r = client.get("/api/scanner/theta-harvester")
    assert r.status_code == 200
    body = r.json()
    assert body["candidates"] == []
    assert body["as_of"] is None


def test_get_returns_persisted_candidates_scored_high_first(client, seeded_candidates):
    r = client.get("/api/scanner/theta-harvester")
    assert r.status_code == 200
    body = r.json()
    assert body["as_of"] == str(_AS_OF)
    scores = [c["score"] for c in body["candidates"]]
    assert scores == sorted(scores, reverse=True)
    # A live IB quote is opt-in; the read path never triggers one.
    assert all(c["credit_ib"] is None for c in body["candidates"])
    # The BS mark is the markout basis and must always be present.
    assert all(c["entry_credit_theo"] > 0 for c in body["candidates"])


def test_get_honours_the_limit_parameter(client, seeded_candidates):
    assert (
        len(client.get("/api/scanner/theta-harvester?limit=1").json()["candidates"])
        == 1
    )


def test_get_returns_short_position_greek_signs(client, seeded_candidates):
    """Positive theta and negative gamma — the position, not the contracts.

    If these ever flip, the sign convention has regressed to the long-contract
    one the grid stores, and every gate downstream silently inverts.
    """
    c = client.get("/api/scanner/theta-harvester").json()["candidates"][0]
    assert c["theta"] > 0
    assert c["gamma"] < 0
    assert c["vega"] < 0


def test_quote_refuses_to_exceed_the_ib_line_budget(client, seeded_candidates):
    # The IB line cap is shared with the spot feed; an unbounded quote loop
    # would starve it. Over-large requests are rejected, never truncated.
    r = client.post("/api/scanner/theta-harvester/quote", json={"limit": 50})
    assert r.status_code == 400
    assert "8" in r.json()["detail"]


def test_rescan_returns_409_while_another_scan_holds_the_lock(
    client, seeded_candidates
):
    """Single-flight: two clicks must not race two watchlist sweeps."""
    settings_dsn = _dsn_from(client)
    with psycopg.connect(settings_dsn) as holder:
        holder.execute(
            "SELECT pg_advisory_lock("
            "('x' || substr(md5('theta_harvester_scan'), 1, 16))::bit(64)::bigint)"
        )
        r = client.post("/api/scanner/theta-harvester/rescan")
        assert r.status_code == 409
        assert "already running" in r.json()["detail"]


def _dsn_from(client) -> str:
    from uw_scan.api.deps import get_settings

    return client.app.dependency_overrides[get_settings]().db_dsn()
