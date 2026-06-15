"""run_detectors persists a markout-ready watchlist snapshot (additive)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from uw_scan.config import Settings
from uw_scan.models import FlowAlert
from uw_scan.scanner.pipeline import run_detectors
from uw_scan.storage.repository import Repository
from uw_scan.storage.signals_repository import SignalsRepository


def test_run_detectors_persists_watchlist_snapshot(seeded_db_empty_cards):
    repo: Repository = seeded_db_empty_cards
    settings = Settings.from_env()
    sigs = SignalsRepository(repo.conn, schema="uw_scan")
    run_id = repo.insert_scan_run("AAPL", notes="")

    # Persist a qualifying flow alert so DCF emits a candidate.
    repo.insert_flow_events(
        run_id,
        "AAPL",
        [
            FlowAlert(
                id="a1",
                ticker="AAPL",
                type="call",
                expiry=date(2026, 9, 18),
                strike=Decimal("200"),
                underlying_price=Decimal("190"),
                total_premium=Decimal("2000000"),
                total_ask_side_prem=Decimal("1900000"),
                total_bid_side_prem=Decimal("100000"),
                volume=5000,
                open_interest=1000,
                next_earnings_date=date(2026, 12, 31),
            )
        ],
    )
    repo.conn.commit()

    cand = run_detectors(
        repo=repo,
        signals_repo=sigs,
        settings=settings,
        run_id=run_id,
        ticker="AAPL",
        today=date(2026, 6, 15),
    )
    repo.conn.commit()
    assert cand is not None

    with repo.conn.cursor() as cur:
        cur.execute(
            "SELECT section, score_model, is_type_f "
            "FROM uw_scan.scanner_candidate_snapshots "
            "WHERE run_id=%s AND ticker='AAPL'",
            (run_id,),
        )
        row = cur.fetchone()
    assert row is not None
    assert row[0] == "watchlist"
    assert row[1] == "watchlist_tier_v1"
