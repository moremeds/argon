"""Integration tests for `storage.repository` against a real Postgres instance.

Uses `pytest-postgresql` to spin up an isolated DB per test. Migration is applied
fresh in each fixture. Fake-cursor tests are explicitly banned by the
Implementation Guardrails — every assertion below hits a real DB.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest
from pytest_postgresql import factories

from uw_scan import models
from uw_scan.storage.repository import Repository

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "uw_scan"
    / "storage"
    / "migrations"
    / "001_s1_core_tables.sql"
)

postgresql_my_proc = factories.postgresql_proc(load=[])
postgresql_my = factories.postgresql("postgresql_my_proc")


@pytest.fixture
def repo(postgresql_my):
    """Open a psycopg connection to the isolated test DB and apply the S1 migration."""
    dsn = (
        f"host={postgresql_my.info.host} port={postgresql_my.info.port} "
        f"dbname={postgresql_my.info.dbname} user={postgresql_my.info.user}"
    )
    if postgresql_my.info.password:
        dsn += f" password={postgresql_my.info.password}"
    conn = psycopg.connect(dsn)
    migration_sql = MIGRATION_PATH.read_text()
    with conn.cursor() as cur:
        cur.execute(migration_sql)
    conn.commit()
    r = Repository(conn, schema="uw_scan")
    try:
        yield r
    finally:
        conn.close()


def test_migration_creates_expected_tables(repo: Repository):
    """The S1 migration must create at least the 22 core tables."""
    with repo.conn.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='uw_scan' ORDER BY table_name"
        )
        tables = {row[0] for row in cur.fetchall()}
    required = {
        "scan_runs",
        "api_request_audit",
        "raw_payloads",
        "flow_events",
        "iv_rank_history",
        "volatility_stats_history",
        "realized_volatility_history",
        "iv_term_snapshots",
        "interpolated_iv_snapshots",
        "risk_reversal_skew_history",
        "greeks_by_expiry_strike",
        "exposures_by_expiry_strike",
        "oi_by_strike",
        "oi_change_events",
        "max_pain_by_expiry",
        "option_contract_snapshots",
        "dark_pool_events",
        "short_interest_snapshots",
        "opportunity_scores",
        "structure_ideas",
        "option_surface_snapshots",
        "oi_by_expiry",
    }
    missing = required - tables
    assert not missing, f"missing tables: {missing}"


def test_insert_scan_run_returns_int_id(repo: Repository):
    run_id = repo.insert_scan_run("TSLA", notes="integration test")
    assert isinstance(run_id, int) and run_id > 0
    repo.conn.commit()


def test_audit_and_raw_payload_roundtrip(repo: Repository):
    run_id = repo.insert_scan_run("TSLA")
    now = datetime.now(UTC)
    audit_id = repo.insert_audit_row(
        run_id=run_id,
        endpoint_slug="flow_alerts",
        endpoint_path="/api/option-trades/flow-alerts",
        params={"ticker_symbol": "TSLA", "limit": 100},
        status_code=200,
        started_at=now,
        finished_at=now,
        daily_req_count=346,
        minute_req_remaining=119,
        minute_req_reset="60000",
    )
    assert isinstance(audit_id, int) and audit_id > 0
    payload_id = repo.insert_raw_payload(audit_id, {"data": [{"x": 1}]})
    assert isinstance(payload_id, int) and payload_id > 0
    repo.conn.commit()

    with repo.conn.cursor() as cur:
        cur.execute(
            "SELECT endpoint_slug, status_code, minute_req_remaining "
            "FROM uw_scan.api_request_audit WHERE audit_id = %s",
            (audit_id,),
        )
        row = cur.fetchone()
    assert row == ("flow_alerts", 200, 119)


def test_flow_events_persisted(repo: Repository):
    run_id = repo.insert_scan_run("TSLA")
    alert = models.FlowAlert(
        id="abc-123",
        ticker="TSLA",
        created_at=datetime.now(UTC),
        option_chain="TSLA260417C00450000",
        strike=Decimal("450"),
        expiry=date(2026, 4, 17),
        type="call",
        total_premium=Decimal("123456.78"),
        total_size=42,
        total_ask_side_prem=Decimal("100000"),
        total_bid_side_prem=Decimal("23456.78"),
        volume=42,
        open_interest=1000,
        has_sweep=True,
        has_multileg=False,
        has_floor=False,
    )
    n = repo.insert_flow_events(run_id, "TSLA", [alert])
    assert n == 1
    repo.conn.commit()

    with repo.conn.cursor() as cur:
        cur.execute(
            "SELECT ticker, has_sweep, has_multileg "
            "FROM uw_scan.flow_events WHERE run_id=%s",
            (run_id,),
        )
        row = cur.fetchone()
    assert row == ("TSLA", True, False)


def test_iv_rank_upsert_is_idempotent(repo: Repository):
    rows = [
        models.IvRankRow(
            ticker="TSLA",
            date=date(2026, 5, 8),
            close=Decimal("428.35"),
            volatility=Decimal("0.41"),
            iv_rank_1y=Decimal("69.18"),
        ),
        models.IvRankRow(
            ticker="TSLA",
            date=date(2026, 5, 9),
            close=Decimal("440.19"),
            volatility=Decimal("0.42"),
            iv_rank_1y=Decimal("70.5"),
        ),
    ]
    n1 = repo.upsert_iv_rank_rows("TSLA", rows)
    n2 = repo.upsert_iv_rank_rows("TSLA", rows)  # re-run should not duplicate
    repo.conn.commit()
    assert n1 == 2
    assert n2 == 2

    with repo.conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM uw_scan.iv_rank_history WHERE ticker = %s",
            ("TSLA",),
        )
        (count,) = cur.fetchone()
    assert count == 2, "upsert duplicated rows"


def test_opportunity_scores_persisted_with_text_array(repo: Repository):
    run_id = repo.insert_scan_run("TSLA")
    repo.insert_opportunity_score(
        run_id,
        "TSLA",
        Decimal("3.5"),
        setup_types=["C"],
        direction="bull",
        confirmations=["dark_pool_size", "atm_call_oi_build"],
        warnings=[],
        notes="strong",
    )
    repo.conn.commit()

    with repo.conn.cursor() as cur:
        cur.execute(
            "SELECT setup_types, confirmations FROM uw_scan.opportunity_scores "
            "WHERE run_id = %s",
            (run_id,),
        )
        setup_types, confirmations = cur.fetchone()
    # psycopg returns text[] as a Python list
    assert setup_types == ["C"]
    assert confirmations == ["dark_pool_size", "atm_call_oi_build"]


def test_deferred_tables_present_but_empty(repo: Repository):
    """`option_surface_snapshots` and `oi_by_expiry` exist but S1 never writes them."""
    assert repo.count_rows("option_surface_snapshots") == 0
    assert repo.count_rows("oi_by_expiry") == 0
