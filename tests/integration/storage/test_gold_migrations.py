"""Smoke test: Phase A1 gold tables exist with PIT-disciplined columns after migrate.

Uses the project's `fresh_schema` pattern (DROP SCHEMA CASCADE + re-run migrate.sh
against the isolated test DB pointed to by UW_SCAN_TEST_DB_NAME). Matches the
pattern in tests/integration/storage/test_migrations.py rather than the
pytest-postgresql fixture variant.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import psycopg
import pytest

from uw_scan.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[3]


def _test_settings() -> Settings:
    test_db = os.environ.get("UW_SCAN_TEST_DB_NAME")
    if not test_db:
        pytest.fail(
            "UW_SCAN_TEST_DB_NAME is not set. Create a dedicated test DB "
            "(e.g. `createdb argon_test`) and export "
            "`UW_SCAN_TEST_DB_NAME=argon_test` before running pytest.",
            pytrace=False,
        )
    os.environ.setdefault("UW_SCAN_API_KEY", "test-dummy-not-used-by-db-tests")
    base = Settings.from_env()
    return base.model_copy(update={"db_name": test_db})


def _run_migrations(settings: Settings) -> None:
    env = {**os.environ, "UW_SCAN_DB_NAME": settings.db_name}
    subprocess.run(
        ["bash", str(REPO_ROOT / "scripts/migrate.sh")],
        check=True,
        cwd=REPO_ROOT,
        env=env,
    )


@pytest.fixture
def fresh_schema():
    settings = _test_settings()
    with psycopg.connect(settings.db_dsn(), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("DROP SCHEMA IF EXISTS uw_scan CASCADE")
            cur.execute("CREATE SCHEMA uw_scan")
    _run_migrations(settings)
    with psycopg.connect(settings.db_dsn()) as conn:
        yield conn


def _table_columns(conn: psycopg.Connection, table: str) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'uw_scan' AND table_name = %s",
            (table,),
        )
        return {row[0] for row in cur.fetchall()}


def test_gold_tables_created(fresh_schema):
    """All gold tables exist with PIT-disciplined columns."""
    expected = {
        "macro_series_daily": {
            "series_id",
            "obs_date",
            "value",
            "as_of",
            "release_date",
            "source",
            "source_url",
        },
        "macro_series_monthly": {
            "series_id",
            "obs_month",
            "value",
            "as_of",
            "release_date",
            "source",
            "source_url",
        },
        "etf_holdings_daily": {
            "ticker",
            "obs_date",
            "holdings_oz",
            "shares_out",
            "nav_per_share",
            "premium_pct",
            "as_of",
            "source",
        },
        "exchange_inventory_daily": {
            "exchange",
            "obs_date",
            "registered_oz",
            "eligible_oz",
            "vault_oz",
            "as_of",
            "source_url",
        },
        "cb_gold_reserves_monthly": {
            "country_iso3",
            "obs_month",
            "reserves_t",
            "bucket",
            "is_reported",
            "is_estimated",
            "as_of",
            "release_date",
            "source",
        },
        "cot_gold_weekly": {
            "obs_date",
            "release_date",
            "mm_long",
            "mm_short",
            "mm_net",
            "comm_long",
            "comm_short",
            "comm_net",
            "open_interest",
            "as_of",
            "source_url",
        },
        "uw_gold_options_daily": {
            "ticker",
            "obs_date",
            "atm_iv_30d",
            "atm_iv_60d",
            "put_25d_iv_30d",
            "call_25d_iv_30d",
            "skew_25d_30d",
            "put_call_oi_ratio",
            "dealer_gamma_est",
            "as_of",
        },
        "gold_posture_daily": {
            # core posture
            "obs_date",
            "computed_at",
            "gauge_corr_60d",
            "gauge_corr_126d",
            "gauge_corr_252d",
            "gauge_corr_504d",
            "gauge_corr_252d_returns",
            "gauge_state",
            "structural_state_label",
            "cb_strategic_12m_sum_t",
            "cb_tactical_12m_sum_t",
            "cb_diversifier_12m_sum_t",
            "gld_holdings_t",
            "gld_30d_net_flow_t",
            "comex_registered_oz",
            "comex_20d_roc_pct",
            "cot_mm_net_pct",
            "cyclical_zone_label",
            "cpi_yoy",
            "t5yifr",
            "dfii10",
            "dfii10_60d_change_bps",
            "factors_jsonb",
            "valuation_flag",
            "real_price_percentile",
            "gold_m2_ratio_percentile",
            "gold_spx_ratio_percentile",
            "structural_posture_text",
            "cyclical_posture_text",
            "valuation_posture_text",
            "inputs_jsonb",
            # GOLD COMPASS extensions
            "structural_posture_chip",
            "cyclical_posture_chip",
            "valuation_posture_chip",
            "spot_jsonb",
            "data_freshness_jsonb",
            "decomposition_jsonb",
            "correlation_history_jsonb",
            "gld_history_jsonb",
            "gold_history_jsonb",
            "row_status",
            "superseded_reason",
        },
    }
    for table, cols in expected.items():
        actual = _table_columns(fresh_schema, table)
        assert actual, f"{table} not created"
        missing = cols - actual
        assert not missing, f"{table} missing columns: {missing}"


def test_gold_migrations_idempotent(fresh_schema):
    """Re-running migrate.sh on a schema that already has the gold tables is a no-op."""
    settings = _test_settings()
    _run_migrations(settings)  # second run

    with psycopg.connect(settings.db_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'uw_scan' "
            "AND table_name IN ("
            "  'macro_series_daily', 'macro_series_monthly',"
            "  'etf_holdings_daily', 'exchange_inventory_daily',"
            "  'cb_gold_reserves_monthly', 'cot_gold_weekly',"
            "  'uw_gold_options_daily', 'gold_posture_daily'"
            ")"
        )
        present = {row[0] for row in cur.fetchall()}

    assert len(present) == 8, f"expected 8 gold tables after re-migrate, got {present}"


def test_gold_posture_pk_and_index(fresh_schema):
    """gold_posture_daily has the (obs_date, computed_at) PK + replay-friendly index."""
    with fresh_schema.cursor() as cur:
        cur.execute(
            "SELECT a.attname "
            "FROM pg_index i "
            "JOIN pg_attribute a ON a.attrelid = i.indrelid "
            " AND a.attnum = ANY(i.indkey) "
            "WHERE i.indrelid = 'uw_scan.gold_posture_daily'::regclass "
            " AND i.indisprimary"
        )
        pk_cols = {row[0] for row in cur.fetchall()}
    assert pk_cols == {"obs_date", "computed_at"}

    with fresh_schema.cursor() as cur:
        cur.execute(
            "SELECT indexname FROM pg_indexes "
            "WHERE schemaname = 'uw_scan' "
            "AND tablename = 'gold_posture_daily'"
        )
        idx = {row[0] for row in cur.fetchall()}
    assert "idx_gold_posture_daily_latest" in idx
    assert "idx_gold_posture_daily_replay_active" in idx
