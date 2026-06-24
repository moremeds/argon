-- 086_greek_rederive_validation.sql
--
-- Audit trail for the DB->DB re-derive of greek_exposure_daily from the
-- per-strike exposures_by_expiry_strike table (#179). Each row records, for a
-- ticker/date where BOTH the re-derived sum and the stored UW aggregate exist,
-- how far apart they are — proving the per-strike sum matches UW's full-chain
-- aggregate (or quantifying the gap). Idempotent.

SET search_path TO uw_scan, public;

BEGIN;

CREATE TABLE IF NOT EXISTS uw_scan.greek_rederive_validation (
    run_date          DATE NOT NULL,
    ticker            TEXT NOT NULL,
    trade_date        DATE NOT NULL,
    rederived_net_gex NUMERIC(20,4),
    stored_net_gex    NUMERIC(20,4),
    abs_diff          NUMERIC(20,4),
    pct_diff          DOUBLE PRECISION,
    PRIMARY KEY (run_date, ticker, trade_date)
);

CREATE INDEX IF NOT EXISTS ix_greek_rederive_validation_ticker_date
    ON uw_scan.greek_rederive_validation (ticker, trade_date DESC);

COMMIT;
