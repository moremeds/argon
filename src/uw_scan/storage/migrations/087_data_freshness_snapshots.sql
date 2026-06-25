-- 087_data_freshness_snapshots.sql
--
-- Nightly per-table data-DATE freshness audit (#prevention). Complements
-- list_record_health, which keys on WRITE-timestamp columns and skips tables
-- with none (e.g. greek_exposure_daily). This records the newest DATA date and
-- active-watchlist coverage so a silent freeze is caught the morning it starts.
-- Idempotent.

SET search_path TO uw_scan, public;

BEGIN;

CREATE TABLE IF NOT EXISTS uw_scan.data_freshness_snapshots (
    run_date        DATE NOT NULL,
    table_name      TEXT NOT NULL,
    date_col        TEXT NOT NULL,
    scope           TEXT NOT NULL,          -- 'watchlist' | 'subset'
    expected_count  INTEGER NOT NULL,       -- denominator for coverage
    covered_count   INTEGER NOT NULL,       -- distinct tickers with a recent date
    coverage_pct    DOUBLE PRECISION,
    max_data_date   DATE,
    days_stale      INTEGER,
    frozen          BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (run_date, table_name)
);

CREATE INDEX IF NOT EXISTS ix_data_freshness_snapshots_table
    ON uw_scan.data_freshness_snapshots (table_name, run_date DESC);

COMMIT;
