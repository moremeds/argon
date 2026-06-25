-- 088_vrp_macro_entry_grid.sql
-- Nightly cache of SPX's listed-strike grid (real UW strikes) for the ~43-DTE
-- expiry, so the RTH entry-capture birth reads it instead of calling UW (whose
-- daily budget is reliably exhausted by ~08:00 ET, before the 10:00 birth cron).
SET search_path TO uw_scan, public;

BEGIN;

CREATE TABLE IF NOT EXISTS uw_scan.vrp_macro_entry_grid (
    name          TEXT        NOT NULL DEFAULT 'SPX',
    for_date      DATE        NOT NULL,
    chosen_expiry DATE        NOT NULL,
    strikes       NUMERIC[]   NOT NULL,   -- real UW-listed put strikes, sorted asc
    fetched_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (name, for_date),
    -- An empty grid is useless (birth can't bracket a delta target) and would
    -- shadow the stale-fallback. Reject it at the DB so no caller can persist {}.
    CONSTRAINT vrp_macro_entry_grid_nonempty CHECK (cardinality(strikes) > 0)
);

COMMIT;
