-- 092_data_gap_healer.sql
--
-- Exact gap-healer domain: resumable audit/heal runs, gaps-only items, no-data
-- caveats, and a dataset registry (the queryable projection of the Python
-- REGISTRY in reports/data_gap_healer.py, kept in sync via the repository).
-- Complements data_freshness_snapshots (coarse freeze detector) with exact
-- per-ticker/date coverage + budget-aware healing state.
-- Idempotent (CREATE ... IF NOT EXISTS, seed via ON CONFLICT / WHERE NOT EXISTS).

SET search_path TO uw_scan, public;

BEGIN;

CREATE TABLE IF NOT EXISTS uw_scan.data_gap_runs (
    id            BIGSERIAL PRIMARY KEY,
    started_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at   TIMESTAMPTZ,
    mode          TEXT NOT NULL CHECK (mode IN ('audit', 'plan', 'execute')),
    status        TEXT NOT NULL CHECK (status IN ('running', 'complete', 'failed', 'cancelled')),
    start_date    DATE,
    end_date      DATE,
    datasets      TEXT[] NOT NULL DEFAULT '{}',
    uw_budget_cap INTEGER,                         -- the only hard cap; massive/external uncapped
    summary_jsonb JSONB NOT NULL DEFAULT '{}'::jsonb,  -- per-dataset coverage + per-bucket spend
    created_by    TEXT NOT NULL DEFAULT current_user
);

CREATE INDEX IF NOT EXISTS ix_data_gap_runs_status
    ON uw_scan.data_gap_runs (status, started_at DESC);

-- Items hold one row per GAP (miss), never per expected pair. Per-dataset totals
-- live in data_gap_runs.summary_jsonb.
CREATE TABLE IF NOT EXISTS uw_scan.data_gap_items (
    id                 BIGSERIAL PRIMARY KEY,
    run_id             BIGINT NOT NULL REFERENCES uw_scan.data_gap_runs(id) ON DELETE CASCADE,
    dataset            TEXT NOT NULL,
    data_date          DATE,
    ticker             TEXT,
    scope_key          TEXT NOT NULL,
    expected_count     INTEGER,
    covered_count      INTEGER,
    estimated_requests INTEGER NOT NULL DEFAULT 0,
    actual_requests    INTEGER NOT NULL DEFAULT 0,
    status             TEXT NOT NULL CHECK (status IN (
                           'planned', 'running', 'healed', 'no_data',
                           'skipped_budget', 'failed')),
    reason             TEXT,
    attempts           INTEGER NOT NULL DEFAULT 0,
    last_error         TEXT,
    verified_at        TIMESTAMPTZ,
    details_jsonb      JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (run_id, dataset, scope_key)
);

CREATE INDEX IF NOT EXISTS ix_data_gap_items_lookup
    ON uw_scan.data_gap_items (dataset, data_date, ticker, status);
CREATE INDEX IF NOT EXISTS ix_data_gap_items_run_status
    ON uw_scan.data_gap_items (run_id, status);

CREATE TABLE IF NOT EXISTS uw_scan.data_gap_caveats (
    dataset    TEXT NOT NULL,
    ticker     TEXT,
    start_date DATE,
    end_date   DATE,
    reason     TEXT NOT NULL,
    source     TEXT NOT NULL DEFAULT 'manual',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- COALESCE over the nullable cols: a plain UNIQUE treats NULL as distinct, which
-- would break ON CONFLICT idempotency on the SPCX seed (NULL start_date).
CREATE UNIQUE INDEX IF NOT EXISTS uq_data_gap_caveats
    ON uw_scan.data_gap_caveats (
        dataset,
        COALESCE(ticker, ''),
        COALESCE(start_date, DATE '0001-01-01'),
        COALESCE(end_date, DATE '9999-12-31'),
        reason
    );

CREATE TABLE IF NOT EXISTS uw_scan.data_gap_dataset_registry (
    table_name         TEXT PRIMARY KEY,
    dataset_group      TEXT NOT NULL,
    audit_mode         TEXT NOT NULL CHECK (audit_mode IN (
                           'strict_ticker_date', 'strict_session', 'freshness_only',
                           'operational_state', 'provenance', 'research_artifact',
                           'excluded')),
    date_col           TEXT,
    ticker_col         TEXT,
    expected_frequency TEXT,
    provider           TEXT,
    granularity        TEXT,
    healer_adapter     TEXT,
    source_system      TEXT,
    retention_days     INTEGER,
    enabled            BOOLEAN NOT NULL DEFAULT TRUE,
    reason             TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_data_gap_registry_group
    ON uw_scan.data_gap_dataset_registry (dataset_group, audit_mode);

-- Seed the SPCX no-data caveat (the one pure-data caveat; the registry itself is
-- seeded from the Python REGISTRY via repository.sync_dataset_registry).
INSERT INTO uw_scan.data_gap_caveats (dataset, ticker, start_date, end_date, reason, source)
SELECT 'option_surface_grid_daily', 'SPCX', NULL, DATE '2026-06-16',
       'listed after 2026-06-17', 'manual'
WHERE NOT EXISTS (
    SELECT 1 FROM uw_scan.data_gap_caveats
     WHERE dataset = 'option_surface_grid_daily'
       AND ticker = 'SPCX'
       AND start_date IS NULL
       AND end_date = DATE '2026-06-16'
       AND reason = 'listed after 2026-06-17'
);

COMMIT;
