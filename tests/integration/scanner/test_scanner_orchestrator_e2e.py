"""End-to-end orchestrator: insert synthetic flow_events + a posture
row into the test DB, call scanner.run_detectors directly against the
real Repository, verify all three target tables are populated."""

from __future__ import annotations

import os
from datetime import date, timedelta
from decimal import Decimal

from psycopg.types.json import Jsonb

from uw_scan.config import Settings
from uw_scan.scanner.pipeline import run_detectors
from uw_scan.storage.repository import Repository
from uw_scan.storage.signals_repository import SignalsRepository

# UW_SCAN_API_KEY is required by Settings.from_env. The orchestrator
# never reaches out to UW (everything reads from the test DB), so a
# dummy value is fine.
os.environ.setdefault("UW_SCAN_API_KEY", "test-dummy-unused")

TODAY = date(2026, 5, 17)


def _settings() -> Settings:
    return Settings.from_env()


def _insert_qualifying_dcf_alert(conn, run_id: int, ticker: str) -> None:
    """Insert a single FlowAlert row that DCF will qualify."""
    sql = """
        INSERT INTO uw_scan.flow_events
          (run_id, alert_id, ticker, option_type, strike, underlying_price,
           total_premium, total_ask_side_prem, total_bid_side_prem,
           volume, open_interest, has_multileg, expiry, next_earnings_date)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                run_id,
                "alert-1",
                ticker.upper(),
                "call",
                Decimal("100"),
                Decimal("100"),
                Decimal("800000"),
                Decimal("700000"),
                Decimal("100000"),
                2000,
                1000,
                False,
                TODAY + timedelta(days=30),
                TODAY + timedelta(days=60),
            ),
        )


def _insert_posture(conn, chip: str) -> None:
    """Minimal gold_posture_daily row so fetch_gold_posture_latest() works."""
    sql = """
        INSERT INTO uw_scan.gold_posture_daily
          (obs_date, computed_at, gauge_state, structural_posture_chip, inputs_jsonb)
        VALUES (%s, NOW(), %s, %s, %s)
    """
    with conn.cursor() as cur:
        cur.execute(sql, (TODAY, "test", chip, Jsonb({})))


def test_e2e_dcf_only_writes_hit_and_gate(seeded_db_empty_cards):
    repo: Repository = seeded_db_empty_cards
    sigs = SignalsRepository(repo.conn, schema="uw_scan")
    _insert_posture(repo.conn, "NEUTRAL")
    run_id = repo.insert_scan_run("AAPL")
    _insert_qualifying_dcf_alert(repo.conn, run_id, "AAPL")
    repo.conn.commit()

    cand = run_detectors(
        repo=repo,
        signals_repo=sigs,
        settings=_settings(),
        run_id=run_id,
        ticker="AAPL",
        today=TODAY,
    )
    repo.conn.commit()

    assert cand is not None
    assert cand.is_type_f is False
    hits = sigs.fetch_hits_for_run(run_id, "AAPL")
    assert any(h["signal_type"] == "deep_conviction_flow" for h in hits)
    gate = sigs.fetch_gate_for_run(run_id, "AAPL")
    assert gate == {"earnings": "pass", "liquidity": "pass", "regime": "pass"}


def test_e2e_suspended_posture_blocks_with_gate_recorded(seeded_db_empty_cards):
    repo: Repository = seeded_db_empty_cards
    sigs = SignalsRepository(repo.conn, schema="uw_scan")
    _insert_posture(repo.conn, "SUSPENDED")
    run_id = repo.insert_scan_run("AAPL")
    _insert_qualifying_dcf_alert(repo.conn, run_id, "AAPL")
    repo.conn.commit()

    cand = run_detectors(
        repo=repo,
        signals_repo=sigs,
        settings=_settings(),
        run_id=run_id,
        ticker="AAPL",
        today=TODAY,
    )
    repo.conn.commit()

    assert cand is None
    gate = sigs.fetch_gate_for_run(run_id, "AAPL")
    assert gate is not None and gate["regime"] == "block"
    hits = sigs.fetch_hits_for_run(run_id, "AAPL")
    assert hits == []
