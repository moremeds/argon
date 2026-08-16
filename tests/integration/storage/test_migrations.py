"""Verify migrations 003-006 produce the expected schema and seed against an
ISOLATED test database — never against the developer's real `option_wizard` DB.

Uses the shared `seeded_db_empty_cards` fixture (session-scoped migrate +
per-test TRUNCATE+COPY restore from baseline). The post-migration state is
identical to what a fresh `DROP SCHEMA CASCADE` + full migration would
produce, which is what these tests assert against."""

from __future__ import annotations

import psycopg  # noqa: F401 — tests below reference psycopg.errors
import pytest

from uw_scan.storage.migrate_runner import MIGRATIONS_DIR


@pytest.fixture
def fresh_schema(seeded_db_empty_cards):
    """Yields a Repository connection backed by the freshly-migrated schema."""
    yield seeded_db_empty_cards.conn


def test_all_new_tables_exist(fresh_schema):
    expected = {
        "watchlist",
        "watchlist_card",
        "daily_ohlc",
        "intraday_quote",
        "pcr_history",
        "jobs",
        "external_api_requests",
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
    # 006 seeds 54 base; 008 +36; 009 +4 (Optical); 010 +1 (OKLO); 011 +1 (BE);
    # 012 +1 (IREN) = 97 active pre-069. 069 soft-deletes 15 (Defense, Telecom-
    # Media, Airlines + ARKK/ES/SMCI/ZS/DDOG/ABBV/MRK) and inserts 10 (ISRG,
    # HYG, JNK, SLV, AMAT, LRCX, KLAC, SNPS, CDNS, TER) → 92 active.
    assert count == 92


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
        assert "idx_trade_insight_ai_analyses_active_reuse" in indexes
        assert "idx_trade_insight_ai_analyses_succeeded_reuse" in indexes
        assert "status" in indexes["idx_trade_insight_ai_analyses_queue"]
        assert "requested_at" in indexes["idx_trade_insight_ai_analyses_queue"]
        assert (
            "analysis_input_hash"
            in indexes["idx_trade_insight_ai_analyses_active_reuse"]
        )
        assert (
            "status = ANY" in indexes["idx_trade_insight_ai_analyses_active_reuse"]
            or "status IN" in indexes["idx_trade_insight_ai_analyses_active_reuse"]
        )
        assert (
            "analysis_input_hash"
            in indexes["idx_trade_insight_ai_analyses_succeeded_reuse"]
        )
        assert (
            "status = 'succeeded'"
            in indexes["idx_trade_insight_ai_analyses_succeeded_reuse"]
        )


def test_external_api_requests_schema(fresh_schema):
    with fresh_schema.cursor() as cur:
        cur.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'uw_scan'
              AND table_name = 'external_api_requests'
        """)
        columns = {row[0] for row in cur.fetchall()}
        assert {
            "request_id",
            "provider",
            "endpoint_key",
            "method",
            "path_template",
            "path",
            "ticker",
            "params_json",
            "status_code",
            "status_family",
            "request_started_at",
            "request_finished_at",
            "latency_ms",
            "attempt",
            "run_id",
            "job_name",
            "provider_request_id",
            "official_daily_count",
            "official_daily_limit",
            "official_minute_remaining",
            "official_minute_reset",
            "error_message",
            "inserted_at",
        } <= columns

        cur.execute("""
            SELECT conname
            FROM pg_constraint
            WHERE conrelid = 'uw_scan.external_api_requests'::regclass
              AND contype = 'c'
        """)
        constraints = {row[0] for row in cur.fetchall()}
        assert {
            "external_api_requests_provider_check",
            "external_api_requests_method_check",
            "external_api_requests_status_family_check",
            "external_api_requests_latency_nonnegative_check",
            "external_api_requests_attempt_nonnegative_check",
        } <= constraints

        cur.execute("""
            SELECT indexname
            FROM pg_indexes
            WHERE schemaname = 'uw_scan'
              AND tablename = 'external_api_requests'
        """)
        indexes = {row[0] for row in cur.fetchall()}
        assert {
            "external_api_requests_provider_started_idx",
            "external_api_requests_provider_ticker_started_idx",
            "external_api_requests_provider_endpoint_started_idx",
            "external_api_requests_provider_status_started_idx",
        } <= indexes


def test_trade_insight_ai_analyses_provider_column(fresh_schema):
    """Migration 053 adds provider TEXT NOT NULL DEFAULT 'codex' with a CHECK
    constraint restricting values to codex|claude."""
    with fresh_schema.cursor() as cur:
        cur.execute(
            "SELECT column_name, data_type, is_nullable, column_default "
            "FROM information_schema.columns "
            "WHERE table_schema = 'uw_scan' "
            "  AND table_name = 'trade_insight_ai_analyses' "
            "  AND column_name = 'provider'"
        )
        row = cur.fetchone()
    assert row is not None, "provider column missing"
    assert row[1] == "text"
    assert row[2] == "NO"
    assert row[3] is not None and "'codex'" in row[3]


def test_trade_insight_ai_analyses_provider_check_constraint(fresh_schema):
    with fresh_schema.cursor() as cur:
        cur.execute(
            "SELECT pg_get_constraintdef(c.oid) "
            "FROM pg_constraint c "
            "JOIN pg_class t ON c.conrelid = t.oid "
            "JOIN pg_namespace n ON t.relnamespace = n.oid "
            "WHERE n.nspname = 'uw_scan' "
            "  AND t.relname = 'trade_insight_ai_analyses' "
            "  AND c.conname = 'trade_insight_ai_analyses_provider_check'"
        )
        row = cur.fetchone()
    assert row is not None
    assert "codex" in row[0] and "claude" in row[0]


def test_trade_insight_ai_analyses_succeeded_reuse_index_includes_provider(
    fresh_schema,
):
    with fresh_schema.cursor() as cur:
        cur.execute(
            "SELECT indexdef FROM pg_indexes "
            "WHERE schemaname = 'uw_scan' "
            "  AND tablename = 'trade_insight_ai_analyses' "
            "  AND indexname = 'idx_trade_insight_ai_analyses_succeeded_reuse'"
        )
        row = cur.fetchone()
    assert row is not None
    indexdef = row[0]
    assert "provider" in indexdef
    assert "analysis_input_hash" in indexdef
    assert "prompt_version" in indexdef
    assert "model" in indexdef
    assert "succeeded" in indexdef.lower()


def test_trade_insight_ai_analyses_active_reuse_index_includes_provider(
    fresh_schema,
):
    with fresh_schema.cursor() as cur:
        cur.execute(
            "SELECT indexdef FROM pg_indexes "
            "WHERE schemaname = 'uw_scan' "
            "  AND tablename = 'trade_insight_ai_analyses' "
            "  AND indexname = 'idx_trade_insight_ai_analyses_active_reuse'"
        )
        row = cur.fetchone()
    assert row is not None
    indexdef = row[0]
    assert "provider" in indexdef
    assert "queued" in indexdef.lower() and "running" in indexdef.lower()


def test_trade_insight_ai_analyses_provider_queue_index_exists(fresh_schema):
    with fresh_schema.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM pg_indexes "
            "WHERE schemaname = 'uw_scan' "
            "  AND tablename = 'trade_insight_ai_analyses' "
            "  AND indexname = 'idx_trade_insight_ai_analyses_provider_queue'"
        )
        assert cur.fetchone() is not None


_RELEASE_STATUS_INSERT = """
INSERT INTO uw_scan.macro_release_ingest_status (
  source, release_key, release_type, status, event_date, event_class,
  discovery_url, parser_version, last_attempt_at
) VALUES (
  'federal_reserve_fomc', %s, %s, 'discovered', DATE '2020-03-23', %s,
  'https://www.federalreserve.gov/monetarypolicy/fomchistorical2020.htm',
  'migration-test', now()
)
"""


def test_migration_rejects_statement_without_event_class(fresh_schema):
    """A statement is a meeting event and must name which kind it was."""
    with pytest.raises(psycopg.errors.CheckViolation):
        with fresh_schema.transaction():
            fresh_schema.execute(
                _RELEASE_STATUS_INSERT,
                ("fomc-statement:monetary20200323a", "statement", None),
            )


def test_migration_rejects_sep_with_event_class(fresh_schema):
    """A SEP is a publication, not a meeting, so it has no meeting class."""
    with pytest.raises(psycopg.errors.CheckViolation):
        with fresh_schema.transaction():
            fresh_schema.execute(
                _RELEASE_STATUS_INSERT,
                ("fed-sep:fomcprojtabl20200610", "sep", "scheduled_meeting"),
            )


def test_migration_rejects_unknown_statement_event_class(fresh_schema):
    with pytest.raises(psycopg.errors.CheckViolation):
        with fresh_schema.transaction():
            fresh_schema.execute(
                _RELEASE_STATUS_INSERT,
                ("fomc-statement:monetary20200323a", "statement", "emergency"),
            )


def test_migration_requires_ok_status_to_carry_a_success(fresh_schema):
    with pytest.raises(psycopg.errors.CheckViolation):
        with fresh_schema.transaction():
            fresh_schema.execute(
                _RELEASE_STATUS_INSERT.replace("'discovered'", "'ok'"),
                (
                    "fomc-statement:monetary20200323a",
                    "statement",
                    "notation_vote",
                ),
            )


def test_migration_requires_failed_status_to_carry_an_error(fresh_schema):
    with pytest.raises(psycopg.errors.CheckViolation):
        with fresh_schema.transaction():
            fresh_schema.execute(
                _RELEASE_STATUS_INSERT.replace("'discovered'", "'failed'"),
                (
                    "fomc-statement:monetary20200323a",
                    "statement",
                    "notation_vote",
                ),
            )


def test_migration_is_idempotent_for_macro_release_tables(fresh_schema):
    """Re-applying the macro migrations must be a no-op, not an error.

    There is no schema_migrations table, so every file is re-executed on every
    deploy. A non-idempotent statement here would break the migrator on the
    mini, not just in CI.
    """
    for name in (
        "119_macro_artifact_instant_resolution.sql",
        "120_macro_release_ingest_status.sql",
    ):
        sql = (MIGRATIONS_DIR / name).read_text()
        with fresh_schema.transaction():
            fresh_schema.execute(sql)

    with fresh_schema.cursor() as cur:
        cur.execute(
            "SELECT to_regclass('uw_scan.macro_release_ingest_status'), "
            "to_regclass('uw_scan.macro_observation_artifacts')"
        )
        assert all(cur.fetchone())
        cur.execute(
            "SELECT count(*) FROM pg_constraint "
            "WHERE conname = 'macro_observations_semantic_hash_format'"
        )
        assert cur.fetchone()[0] == 1
        cur.execute(
            "SELECT count(*) FROM pg_indexes "
            "WHERE schemaname = 'uw_scan' "
            "AND indexname = 'uq_macro_observations_semantic'"
        )
        assert cur.fetchone()[0] == 1
