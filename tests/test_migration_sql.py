from pathlib import Path


MIGRATION = Path("src/uw_scan/storage/migrations/001_create_uw_scan_schema.sql")


def test_migration_creates_schema_and_version_table():
    sql = MIGRATION.read_text()

    assert "CREATE SCHEMA IF NOT EXISTS uw_scan" in sql
    assert "CREATE TABLE IF NOT EXISTS uw_scan.schema_versions" in sql
    assert "001_create_uw_scan_schema" in sql


def test_migration_uses_compressed_bytea_raw_payloads():
    sql = MIGRATION.read_text()

    assert "CREATE TABLE IF NOT EXISTS uw_scan.raw_payloads" in sql
    assert "payload_compressed BYTEA NOT NULL" in sql
    assert "content_sha256 TEXT NOT NULL" in sql


def test_migration_defines_core_uniqueness_grains():
    sql = MIGRATION.read_text()

    assert "UNIQUE (run_id, option_symbol, fetched_at_utc)" in sql
    assert "UNIQUE (run_id, ticker, market_date, expiry, strike)" in sql
    assert "UNIQUE (run_id, ticker, market_date, expiry)" in sql
