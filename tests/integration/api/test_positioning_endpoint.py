"""GET /api/positioning/{ticker} + /api/positioning/screener — real DB."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from uw_scan.storage.repository import Repository


def _bank_tsla(repo: Repository) -> None:
    repo.upsert_uw_positioning(
        ticker="TSLA",
        snapshot_date=date(2026, 7, 6),
        si_pct_float=Decimal("0.12"),  # elevated -> 1
        si_days_to_cover=Decimal("4.0"),  # elevated -> 1
        si_fee_rate=Decimal("0.50"),  # below -> 0
        analyst_buy=30,
        analyst_hold=10,
        analyst_sell=5,
        analyst_target_avg=Decimal("500.00"),
        insider_net_flow=Decimal("-1250000"),
        earn_reactions_positive=2,
        earn_reactions_total=4,
        next_er_date=date(2026, 8, 15),
    )
    repo.conn.commit()


def test_snapshot_available_with_derived_signals(client, seeded_db_with_cards):
    _bank_tsla(seeded_db_with_cards)
    r = client.get("/api/positioning/TSLA")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True
    assert body["ticker"] == "TSLA"
    assert Decimal(body["si_pct_float"]) == Decimal("0.12")
    # spot 445.12 from the seeded card feeds implied upside.
    assert Decimal(body["spot"]) == Decimal("445.12")
    sig = body["signals"]
    assert sig["squeeze_score"] == 2
    assert sig["squeeze_label"] == "ELEVATED"
    assert sig["insider_tilt"] == "SELLING"
    # (500 - 445.12) / 445.12 * 100 ~= 12.33
    assert Decimal(sig["analyst_implied_upside_pct"]) > Decimal("12")
    assert Decimal(sig["er_positive_base_rate"]) == Decimal("0.5")
    assert sig["days_to_next_er"] == 40


def test_snapshot_unavailable_when_unbanked(client, seeded_db_with_cards):
    r = client.get("/api/positioning/TSLA")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False
    assert body["ticker"] == "TSLA"


def test_screener_lists_banked_watchlist_ticker(client, seeded_db_with_cards):
    _bank_tsla(seeded_db_with_cards)
    r = client.get("/api/positioning/screener")
    assert r.status_code == 200
    body = r.json()
    assert body["as_of"] == "2026-07-06"
    tsla = next((row for row in body["rows"] if row["ticker"] == "TSLA"), None)
    assert tsla is not None
    assert tsla["squeeze_label"] == "ELEVATED"
    assert tsla["insider_tilt"] == "SELLING"
    assert Decimal(tsla["spot"]) == Decimal("445.12")


def test_screener_empty_when_nothing_banked(client, seeded_db_with_cards):
    r = client.get("/api/positioning/screener")
    assert r.status_code == 200
    assert r.json()["rows"] == []
