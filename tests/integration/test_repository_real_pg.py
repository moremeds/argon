"""Integration tests for `storage.repository` against a real Postgres instance.

Uses `pytest-postgresql` to spin up an isolated DB per test. Migration is applied
fresh in each fixture. Fake-cursor tests are explicitly banned by the
Implementation Guardrails — every assertion below hits a real DB.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest
from pytest_postgresql import factories

from uw_scan import models
from uw_scan.storage.repository import Repository

MIGRATIONS_DIR = (
    Path(__file__).resolve().parents[2] / "src" / "uw_scan" / "storage" / "migrations"
)

postgresql_my_proc = factories.postgresql_proc(load=[])
postgresql_my = factories.postgresql("postgresql_my_proc")


@pytest.fixture
def repo(postgresql_my):
    """Open a psycopg connection to the isolated test DB and apply every migration
    in lexical order — same order `scripts/migrate.sh` uses in prod/dev. Tests on
    this fixture see the current schema, not a frozen S1+S2 snapshot.
    """
    dsn = (
        f"host={postgresql_my.info.host} port={postgresql_my.info.port} "
        f"dbname={postgresql_my.info.dbname} user={postgresql_my.info.user}"
    )
    if postgresql_my.info.password:
        dsn += f" password={postgresql_my.info.password}"
    # Apply migrations via psql, the same way scripts/migrate.sh does in
    # prod/dev. psycopg wraps multi-statement execute() calls in implicit
    # transactions, which breaks statements like DROP INDEX CONCURRENTLY.
    for sql_path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        subprocess.run(
            ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-f", str(sql_path)],
            check=True,
            capture_output=True,
        )
    conn = psycopg.connect(dsn)
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


def test_batch_writer_methods_preserve_real_db_behavior(repo: Repository):
    run_id = repo.insert_scan_run("TSLA")

    assert repo.insert_iv_term_rows(run_id, []) == 0
    assert repo.insert_greek_exposure_rows(run_id, "TSLA", []) == 0
    assert repo.insert_greeks_rows(run_id, "TSLA", []) == 0
    assert repo.insert_option_contract_rows(run_id, "TSLA", []) == 0
    assert repo.upsert_iv_rank_rows("TSLA", []) == 0
    assert repo.upsert_volatility_stats_rows([]) == 0
    assert repo.upsert_realized_vol_rows("TSLA", []) == 0
    assert repo.upsert_skew_rows("TSLA", []) == 0
    assert repo.insert_flow_events(run_id, "TSLA", []) == 0

    term_rows = [
        models.TermStructureRow(
            ticker="TSLA",
            date=date(2026, 5, 18),
            expiry=date(2026, 6, 19),
            dte=32,
            volatility=Decimal("0.42"),
        ),
        models.TermStructureRow(
            ticker="TSLA",
            date=date(2026, 5, 18),
            expiry=date(2026, 7, 17),
            dte=60,
            volatility=Decimal("0.51"),
        ),
    ]
    exposure_rows = [
        models.GreekExposureRow(
            date=date(2026, 5, 18),
            expiry=date(2026, 6, 19),
            strike=Decimal("450"),
            call_gex=Decimal("1000"),
        ),
        models.GreekExposureRow(
            date=date(2026, 5, 18),
            expiry=date(2026, 6, 19),
            strike=Decimal("460"),
            call_gex=Decimal("1100"),
        ),
    ]
    greeks_rows = [
        models.GreeksRow(
            date=date(2026, 5, 18),
            expiry=date(2026, 6, 19),
            strike=Decimal("450"),
            call_delta=Decimal("0.51"),
        ),
        models.GreeksRow(
            date=date(2026, 5, 18),
            expiry=date(2026, 6, 19),
            strike=Decimal("460"),
            call_delta=Decimal("0.45"),
        ),
    ]
    contract_rows = [
        models.OptionContractRow(
            option_symbol="TSLA260619C00450000",
            last_price=Decimal("12.1"),
            volume=300,
        ),
        models.OptionContractRow(
            option_symbol="TSLA260619P00450000",
            last_price=Decimal("10.2"),
            volume=200,
        ),
    ]
    iv_rank_rows = [
        models.IvRankRow(date=date(2026, 5, 18), close=Decimal("450")),
        models.IvRankRow(date=date(2026, 5, 19), close=Decimal("455")),
    ]
    vol_stats_rows = [
        models.VolStatsRow(ticker="TSLA", date=date(2026, 5, 18), iv=Decimal("0.42")),
        models.VolStatsRow(ticker="TSLA", date=date(2026, 5, 19), iv=Decimal("0.43")),
    ]
    realized_rows = [
        models.RealizedVolRow(date=date(2026, 5, 18), price=Decimal("450")),
        models.RealizedVolRow(date=date(2026, 5, 19), price=Decimal("455")),
    ]
    skew_rows = [
        models.SkewRow(
            ticker="TSLA",
            date=date(2026, 5, 18),
            delta=25,
            expiry=date(2026, 6, 19),
            risk_reversal=Decimal("-0.04"),
        ),
        models.SkewRow(
            ticker="TSLA",
            date=date(2026, 5, 18),
            delta=25,
            expiry=date(2026, 7, 17),
            risk_reversal=Decimal("-0.05"),
        ),
    ]
    flow_alerts = [
        models.FlowAlert(
            id="flow-1",
            ticker="TSLA",
            created_at=datetime(2026, 5, 18, 14, 30, tzinfo=UTC),
            total_premium=Decimal("100"),
        ),
        models.FlowAlert(
            id="flow-2",
            ticker="TSLA",
            created_at=datetime(2026, 5, 18, 14, 31, tzinfo=UTC),
            total_premium=Decimal("200"),
        ),
    ]

    writer_calls = [
        lambda: repo.insert_iv_term_rows(run_id, term_rows),
        lambda: repo.insert_greek_exposure_rows(run_id, "TSLA", exposure_rows),
        lambda: repo.insert_greeks_rows(run_id, "TSLA", greeks_rows),
        lambda: repo.insert_option_contract_rows(run_id, "TSLA", contract_rows),
        lambda: repo.upsert_iv_rank_rows("TSLA", iv_rank_rows),
        lambda: repo.upsert_volatility_stats_rows(vol_stats_rows),
        lambda: repo.upsert_realized_vol_rows("TSLA", realized_rows),
        lambda: repo.upsert_skew_rows("TSLA", skew_rows),
        lambda: repo.insert_flow_events(run_id, "TSLA", flow_alerts),
    ]
    for call_writer in writer_calls:
        assert call_writer() == 2
        assert call_writer() == 2
    repo.conn.commit()

    with repo.conn.cursor() as cur:
        cur.execute(
            "SELECT expiry, volatility FROM uw_scan.iv_term_snapshots "
            "WHERE run_id=%s ORDER BY expiry",
            (run_id,),
        )
        assert cur.fetchall() == [
            (date(2026, 6, 19), Decimal("0.42")),
            (date(2026, 7, 17), Decimal("0.51")),
        ]

        cur.execute(
            "SELECT strike, call_gex FROM uw_scan.exposures_by_expiry_strike "
            "WHERE run_id=%s ORDER BY strike",
            (run_id,),
        )
        assert cur.fetchall() == [
            (Decimal("450"), Decimal("1000")),
            (Decimal("460"), Decimal("1100")),
        ]

        cur.execute(
            "SELECT strike, call_delta FROM uw_scan.greeks_by_expiry_strike "
            "WHERE run_id=%s ORDER BY strike",
            (run_id,),
        )
        assert cur.fetchall() == [
            (Decimal("450"), Decimal("0.51")),
            (Decimal("460"), Decimal("0.45")),
        ]

        cur.execute(
            "SELECT option_symbol, last_price, volume "
            "FROM uw_scan.option_contract_snapshots WHERE run_id=%s "
            "ORDER BY option_symbol",
            (run_id,),
        )
        assert cur.fetchall() == [
            ("TSLA260619C00450000", Decimal("12.1"), 300),
            ("TSLA260619P00450000", Decimal("10.2"), 200),
        ]

        cur.execute(
            "SELECT market_date, close FROM uw_scan.iv_rank_history "
            "WHERE ticker=%s ORDER BY market_date",
            ("TSLA",),
        )
        assert cur.fetchall() == [
            (date(2026, 5, 18), Decimal("450")),
            (date(2026, 5, 19), Decimal("455")),
        ]

        cur.execute(
            "SELECT market_date, iv FROM uw_scan.volatility_stats_history "
            "WHERE ticker=%s ORDER BY market_date",
            ("TSLA",),
        )
        assert cur.fetchall() == [
            (date(2026, 5, 18), Decimal("0.42")),
            (date(2026, 5, 19), Decimal("0.43")),
        ]

        cur.execute(
            "SELECT market_date, price FROM uw_scan.realized_volatility_history "
            "WHERE ticker=%s ORDER BY market_date",
            ("TSLA",),
        )
        assert cur.fetchall() == [
            (date(2026, 5, 18), Decimal("450")),
            (date(2026, 5, 19), Decimal("455")),
        ]

        cur.execute(
            "SELECT expiry, risk_reversal FROM uw_scan.risk_reversal_skew_history "
            "WHERE ticker=%s ORDER BY expiry",
            ("TSLA",),
        )
        assert cur.fetchall() == [
            (date(2026, 6, 19), Decimal("-0.04")),
            (date(2026, 7, 17), Decimal("-0.05")),
        ]

        cur.execute(
            "SELECT alert_id, flow_footprint_label FROM uw_scan.flow_events "
            "WHERE run_id=%s ORDER BY alert_id",
            (run_id,),
        )
        assert cur.fetchall() == [
            ("flow-1", "unclassified"),
            ("flow-2", "unclassified"),
        ]


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


def test_s2_migration_creates_scan_tables(repo: Repository):
    """The S2 migration adds `scan_universe` and `scan_results` to the schema."""
    with repo.conn.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='uw_scan' AND table_name IN "
            "('scan_universe','scan_results')"
        )
        tables = {row[0] for row in cur.fetchall()}
    assert tables == {"scan_universe", "scan_results"}


def test_insert_scan_universe_and_results_roundtrip(repo: Repository):
    """Repository.insert_scan_universe + insert_scan_results persist + fetch back."""
    run_id = repo.insert_scan_run("__FULL_SCAN__", notes="integration s2")
    repo.insert_scan_universe(run_id, ["TSLA", "NVDA", "AAPL"])

    sr_tsla = models.BulkScreenerRow(
        ticker="TSLA",
        date=date(2026, 5, 11),
        sector="Consumer Cyclical",
        net_call_premium=Decimal("100000000"),
        net_put_premium=Decimal("0"),
        iv_rank=Decimal("80"),
        gex_net_change=Decimal("50000"),
        total_open_interest=1_000_000,
        variance_risk_premium=Decimal("-0.07"),
    )
    result = models.ScanTickerResult(
        ticker="TSLA",
        setup_type="F",
        label="Multi-Signal Confluence",
        direction="bull",
        score=Decimal("4.5"),
        net_premium=Decimal("100000000"),
        net_call_premium=Decimal("100000000"),
        net_put_premium=Decimal("0"),
        iv_rank=Decimal("80"),
        sector="Consumer Cyclical",
        gex_net_change=Decimal("50000"),
        variance_risk_premium=Decimal("-0.07"),
        total_open_interest=1_000_000,
        signals_present=["gex_oi_shift=0.05", "vrp_anomaly=-0.07"],
        confirmations=["net premium = $100M (bull)", "iv_rank = 80"],
        warnings=[],
        notes="Type F",
        screener_row=sr_tsla,
    )
    n = repo.insert_scan_results(run_id, [result])
    assert n == 1
    repo.conn.commit()

    universe = repo.fetch_scan_universe(run_id)
    assert {u["ticker"] for u in universe} == {"TSLA", "NVDA", "AAPL"}

    results = repo.fetch_scan_results(run_id)
    assert len(results) == 1
    row = results[0]
    assert row["ticker"] == "TSLA"
    assert row["setup_type"] == "F"
    assert row["direction"] == "bull"
    assert row["signals_present"] == [
        "gex_oi_shift=0.05",
        "vrp_anomaly=-0.07",
    ]
    assert row["confirmations"] == [
        "net premium = $100M (bull)",
        "iv_rank = 80",
    ]
    assert row["sector"] == "Consumer Cyclical"
    assert row["market_date"] == date(2026, 5, 11)
    assert repo.latest_scan_run_id() == run_id
