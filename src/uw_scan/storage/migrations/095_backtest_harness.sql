-- src/uw_scan/storage/migrations/095_backtest_harness.sql
-- Backtest harness persistence: one run per sweep, one row per grid config.
-- Standing rule: every research/backtest trace persists in full, with the
-- exact reproduce command (reproduce_cmd is NOT NULL by design).
SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS backtest_sweep_runs (
    id            BIGSERIAL PRIMARY KEY,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    strategy      TEXT NOT NULL,
    git_sha       TEXT,
    reproduce_cmd TEXT NOT NULL,
    params_grid   JSONB,
    data_start    DATE,
    data_end      DATE,
    status        TEXT NOT NULL DEFAULT 'running',
    error         TEXT,
    notes         TEXT
);

CREATE TABLE IF NOT EXISTS backtest_sweep_results (
    id         BIGSERIAL PRIMARY KEY,
    run_id     BIGINT NOT NULL REFERENCES backtest_sweep_runs(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    config     JSONB NOT NULL,
    metrics    JSONB,
    gates      JSONB,
    n_trades   INTEGER,
    status     TEXT NOT NULL DEFAULT 'ok',
    error      TEXT
);

CREATE INDEX IF NOT EXISTS idx_backtest_sweep_results_run
    ON backtest_sweep_results (run_id);
