-- Budgeted dark/lit print history backfill (worker/jobs/dark_lit_backfill.py).
-- Two bookkeeping tables, no data change: the job writes the prints themselves
-- into uw_dark_lit_flow_prints through capture_dark_lit_for.

-- One row per finished ticker-day. 'done' = paged to the session's first print;
-- 'unavailable' = UW answered historic_data_access_missing (outside its rolling
-- 730-trading-day window). The job skips every ticker-day listed here, which is
-- what makes it resumable.
CREATE TABLE IF NOT EXISTS uw_scan.dark_lit_backfill_progress (
    ticker       TEXT        NOT NULL,
    market_date  DATE        NOT NULL,
    status       TEXT        NOT NULL CHECK (status IN ('done', 'unavailable')),
    pages        INTEGER     NOT NULL DEFAULT 0,
    rows_written INTEGER     NOT NULL DEFAULT 0,
    finished_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, market_date)
);

-- One row per run: what it spent, what it finished, what is left.
CREATE TABLE IF NOT EXISTS uw_scan.dark_lit_backfill_runs (
    id                BIGSERIAL   PRIMARY KEY,
    started_at        TIMESTAMPTZ NOT NULL,
    finished_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    budget_day        DATE        NOT NULL,  -- UW budget day (UTC)
    quota             INTEGER     NOT NULL,
    calls             INTEGER     NOT NULL,  -- this run's UW calls
    ticker_days_done  INTEGER     NOT NULL,
    unavailable       INTEGER     NOT NULL,
    errors            INTEGER     NOT NULL,
    remaining         INTEGER,               -- pending ticker-days left; NULL if unknown
    stop_reason       TEXT        NOT NULL
);
