"""Integration tests for _SkewMixin (pytest-postgresql)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest


@pytest.fixture
def repo(seeded_db_empty_cards):
    """Alias: the canonical bare-Repository fixture (see tests/integration/conftest.py)."""
    return seeded_db_empty_cards


def _snap(ticker: str, d: date, **over) -> dict:
    base = {
        "ticker": ticker,
        "market_date": d,
        "basis": "eod",
        "spot": Decimal("100"),
        "rr_25d": Decimal("0.01"),
        "skew_25d": Decimal("0.01"),
        "rr_z_180d": Decimal("1.7"),
        "rr_pct_252d": Decimal("90"),
        "deviation_class": "RICH",
        "skew_term_class": "flat",
        "front_rr": Decimal("0.01"),
        "back_rr": None,
        "rho_spotvol_63d": Decimal("-0.4"),
        "rho_spotvol_21d": Decimal("-0.5"),
        "rho_sign": -1,
        "drive_class": "PANIC",
        "asset_class": "single_name",
        "class_expected_sign": "mixed",
        "borrow_flag": "normal",
        "borrow_fee_rate": Decimal("0.25"),
        "days_to_cover": Decimal("1.5"),
        "earnings_gate": "pass",
        "regime": "HIGH_VOL",
        "directional_lean": "NEUTRAL",
        "lean_confidence": "low",
        "lean_basis": "no verdict",
        "read_summary": "test",
        "read_json": {"k": "v"},
    }
    base.update(over)
    return base


def test_upsert_snapshot_is_idempotent(repo):
    d = date(2026, 6, 1)
    assert repo.upsert_skew_analytics_snapshots([_snap("AAPL", d)]) == 1
    repo.upsert_skew_analytics_snapshots([_snap("AAPL", d, rr_25d=Decimal("0.02"))])
    repo.conn.commit()
    latest = repo.get_skew_analytics_latest("AAPL")
    assert latest is not None
    assert latest["rr_25d"] == Decimal("0.02")  # updated, not duplicated


def test_history_returns_ascending(repo):
    repo.upsert_skew_analytics_snapshots(
        [_snap("MSFT", date(2026, 5, 1)), _snap("MSFT", date(2026, 5, 2))]
    )
    repo.conn.commit()
    rows = repo.fetch_skew_analytics_history("MSFT", days=400)
    assert [r["market_date"] for r in rows] == [date(2026, 5, 1), date(2026, 5, 2)]


def test_verdict_roundtrip(repo):
    repo.upsert_skew_directional_verdict(
        asset_class="single_name",
        deviation_class="RICH",
        drive_class="PANIC",
        regime="HIGH_VOL",
        verdict="TRADABLE_BEAR",
        confidence="med",
        forward_sep=Decimal("-0.021"),
        n=42,
        borrow_clean=True,
        survives_gate=True,
        as_of=date(2026, 6, 1),
    )
    repo.conn.commit()
    v = repo.get_skew_directional_verdict(
        asset_class="single_name",
        deviation_class="RICH",
        drive_class="PANIC",
        regime="HIGH_VOL",
    )
    assert v is not None and v["verdict"] == "TRADABLE_BEAR" and v["n"] == 42
    assert (
        repo.get_skew_directional_verdict(
            asset_class="index_macro",
            deviation_class="RICH",
            drive_class="PANIC",
            regime="HIGH_VOL",
        )
        is None
    )


def test_latest_next_earnings_date(repo):
    # flow_events requires run_id (FK -> scan_runs) + alert_id (NOT NULL),
    # UNIQUE(run_id, alert_id). Latest non-null next_earnings_date wins.
    run_id = repo.insert_scan_run(ticker="NFLX")
    with repo.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO uw_scan.flow_events "
            "(run_id, alert_id, ticker, next_earnings_date, inserted_at) "
            "VALUES (%s, 'a1', 'NFLX', %s, now() - interval '2 days'), "
            "       (%s, 'a2', 'NFLX', %s, now())",
            (run_id, date(2026, 7, 1), run_id, date(2026, 7, 15)),
        )
    repo.conn.commit()
    assert repo.fetch_latest_next_earnings_date("NFLX") == date(2026, 7, 15)
    assert repo.fetch_latest_next_earnings_date("ZZZZ") is None


def test_fetch_watchlist_sector(repo):
    with repo.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO uw_scan.watchlist (ticker, sector) VALUES ('ZZTOP', 'Macro') "
            "ON CONFLICT (ticker) DO UPDATE SET sector='Macro', removed_at=NULL"
        )
    repo.conn.commit()
    assert repo.fetch_watchlist_sector("ZZTOP") == "Macro"
    assert repo.fetch_watchlist_sector("NOPE") is None
