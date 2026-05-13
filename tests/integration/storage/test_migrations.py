"""Verify migrations 003-006 produce the expected schema and seed against an
ISOLATED test database — never against the developer's real `option_wizard` DB.

Requires `UW_SCAN_TEST_DB_NAME` env var to point at a dedicated test database
(e.g. `option_wizard_test`). The fixture refuses to run if it isn't set, so
running `pytest` cannot destroy local scan data by accident."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import psycopg
import pytest

from uw_scan.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[3]


def _test_settings() -> Settings:
    """Return a Settings instance pointing at the isolated test DB.

    HARD REQUIREMENT: the developer must set UW_SCAN_TEST_DB_NAME to a database
    name that is NOT their working `option_wizard` DB. The fixture refuses to
    run otherwise — protects against `DROP SCHEMA` against the wrong target.

    DB-only tests (migrations, repository) don't need a UW API key. We inject
    a dummy `UW_SCAN_API_KEY` before calling `Settings.from_env()` so the
    `RuntimeError("UW_SCAN_API_KEY is not set")` from config.py doesn't fail
    fresh dev/CI environments.
    """
    test_db = os.environ.get("UW_SCAN_TEST_DB_NAME")
    if not test_db:
        pytest.fail(
            "UW_SCAN_TEST_DB_NAME is not set. Create a dedicated test DB "
            "(e.g. `createdb option_wizard_test`) and export "
            "`UW_SCAN_TEST_DB_NAME=option_wizard_test` before running pytest. "
            "This fixture refuses to operate on the working DB because it "
            "performs `DROP SCHEMA uw_scan CASCADE`.",
            pytrace=False,
        )
    os.environ.setdefault("UW_SCAN_API_KEY", "test-dummy-not-used-by-db-tests")
    base = Settings.from_env()
    return base.model_copy(update={"db_name": test_db})


@pytest.fixture
def fresh_schema():
    """DROP + CREATE uw_scan schema on the TEST database, then re-apply all
    migrations. Yields a connection."""
    settings = _test_settings()
    with psycopg.connect(settings.db_dsn(), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("DROP SCHEMA IF EXISTS uw_scan CASCADE")
            cur.execute("CREATE SCHEMA uw_scan")
    env = {**os.environ, "UW_SCAN_DB_NAME": settings.db_name}
    subprocess.run(
        ["bash", str(REPO_ROOT / "scripts/migrate.sh")],
        check=True,
        cwd=REPO_ROOT,
        env=env,
    )
    with psycopg.connect(settings.db_dsn()) as conn:
        yield conn


def test_all_new_tables_exist(fresh_schema):
    expected = {
        "watchlist",
        "watchlist_card",
        "daily_ohlc",
        "intraday_quote",
        "pcr_history",
        "jobs",
    }
    with fresh_schema.cursor() as cur:
        cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='uw_scan'")
        actual = {row[0] for row in cur.fetchall()}
    assert expected <= actual, f"missing: {expected - actual}"


def test_strike_gex_curve_column_added(fresh_schema):
    with fresh_schema.cursor() as cur:
        cur.execute("""
            SELECT data_type FROM information_schema.columns
            WHERE table_schema='uw_scan'
              AND table_name='scan_runs'
              AND column_name='strike_gex_curve'
        """)
        row = cur.fetchone()
    assert row is not None, "strike_gex_curve column missing"
    assert row[0] == "jsonb"


def test_watchlist_seeded(fresh_schema):
    with fresh_schema.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM uw_scan.watchlist WHERE removed_at IS NULL")
        row = cur.fetchone()
        assert row is not None
        count = row[0]
    # 006 seeds 54 base tickers; 008 adds 36 more; 009 adds 4 optical
    # (AAOI, ALAB, COHR, FN); 010 adds OKLO; 011 adds BE = 96 active rows.
    assert count == 96


def test_watchlist_card_fk_to_scan_runs(fresh_schema):
    with fresh_schema.cursor() as cur:
        cur.execute("""
            SELECT confrelid::regclass::text
            FROM pg_constraint
            WHERE conrelid = 'uw_scan.watchlist_card'::regclass
              AND contype = 'f'
              AND 'run_id' = ANY(
                SELECT attname FROM pg_attribute
                WHERE attrelid = 'uw_scan.watchlist_card'::regclass
                  AND attnum = ANY(conkey)
              )
        """)
        targets = [row[0] for row in cur.fetchall()]
    assert "uw_scan.scan_runs" in targets, (
        f"watchlist_card.run_id FK missing or wrong target: {targets}"
    )


def test_jobs_status_check_constraint(fresh_schema):
    with fresh_schema.cursor() as cur:
        cur.execute("""
            INSERT INTO uw_scan.watchlist(ticker, sector) VALUES ('TEST', 'ETF')
            ON CONFLICT (ticker) DO NOTHING
        """)
        fresh_schema.commit()
        with pytest.raises(psycopg.errors.CheckViolation):
            cur.execute(
                "INSERT INTO uw_scan.jobs(ticker, status) VALUES (%s, %s)",
                ("TEST", "bogus_status"),
            )
            fresh_schema.commit()


def test_trade_insight_ai_analysis_schema(fresh_schema):
    with fresh_schema.cursor() as cur:
        cur.execute("""
            SELECT to_regclass('uw_scan.trade_insight_ai_analyses')
        """)
        assert cur.fetchone()[0] == "uw_scan.trade_insight_ai_analyses"

        cur.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'uw_scan'
              AND table_name = 'trade_insight_ai_analyses'
        """)
        columns = {row[0] for row in cur.fetchall()}
        assert {
            "trade_insights_input_hash",
            "analysis_input_hash",
            "analysis_input_jsonb",
            "prompt_text",
            "prompt_payload_jsonb",
            "output_schema_jsonb",
            "produced_at",
        } <= columns

        cur.execute("""
            INSERT INTO uw_scan.scan_runs(ticker, status)
            VALUES ('TSLA', 'finished')
            RETURNING run_id
        """)
        run_id = cur.fetchone()[0]
        cur.execute(
            """
            INSERT INTO uw_scan.trade_insight_snapshots(
                run_id,
                ticker,
                assembler_version,
                input_hash,
                payload_jsonb
            )
            VALUES (%s, 'TSLA', 'trade-insights-v1', 'ti-hash', '{}'::jsonb)
            RETURNING snapshot_id
            """,
            (run_id,),
        )
        snapshot_id = cur.fetchone()[0]
        fresh_schema.commit()

        with pytest.raises(psycopg.errors.CheckViolation):
            cur.execute(
                """
                INSERT INTO uw_scan.trade_insight_ai_analyses(
                    snapshot_id,
                    ticker,
                    run_id,
                    trade_insights_input_hash,
                    analysis_input_hash,
                    analysis_input_jsonb,
                    model,
                    prompt_version,
                    status
                )
                VALUES (
                    %s,
                    'TSLA',
                    %s,
                    'ti-hash',
                    'ai-hash',
                    '{}'::jsonb,
                    'codex-default',
                    'trade-insights-ai-v1',
                    'invalid'
                )
                """,
                (snapshot_id, run_id),
            )
            fresh_schema.commit()
        fresh_schema.rollback()

        cur.execute("""
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE schemaname = 'uw_scan'
              AND tablename = 'trade_insight_ai_analyses'
        """)
        indexes = {row[0]: row[1] for row in cur.fetchall()}
        assert "idx_trade_insight_ai_analyses_queue" in indexes
        assert "idx_trade_insight_ai_analyses_succeeded_reuse" in indexes
        assert "status" in indexes["idx_trade_insight_ai_analyses_queue"]
        assert "requested_at" in indexes["idx_trade_insight_ai_analyses_queue"]
        assert "analysis_input_hash" in indexes[
            "idx_trade_insight_ai_analyses_succeeded_reuse"
        ]
        assert "status = 'succeeded'" in indexes[
            "idx_trade_insight_ai_analyses_succeeded_reuse"
        ]
