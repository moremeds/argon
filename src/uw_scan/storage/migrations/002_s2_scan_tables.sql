-- S2 tables for the Full Scan Report. Additive to 001. Idempotent.
-- Every date/timestamp column carries a COMMENT ON COLUMN documenting its semantics.
-- TEXT[] used for multi-valued columns (not pipe-delimited strings).

SET search_path TO uw_scan, public;

-- ----------------------------------------------------------------------------
-- scan_universe: tickers that participated in a scan run, keyed by run_id.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS uw_scan.scan_universe (
    run_id      BIGINT NOT NULL REFERENCES uw_scan.scan_runs(run_id) ON DELETE CASCADE,
    ticker      TEXT NOT NULL,
    source      TEXT NOT NULL DEFAULT 'hardcoded_s2',
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, ticker)
);

COMMENT ON COLUMN uw_scan.scan_universe.inserted_at IS 'Wall-clock time the row was written.';

-- ----------------------------------------------------------------------------
-- scan_results: per-ticker scoring + setup classification for a scan run.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS uw_scan.scan_results (
    run_id              BIGINT NOT NULL REFERENCES uw_scan.scan_runs(run_id) ON DELETE CASCADE,
    ticker              TEXT NOT NULL,
    market_date         DATE,
    setup_type          TEXT,
    direction           TEXT,
    score               NUMERIC NOT NULL DEFAULT 0,
    net_call_premium    NUMERIC,
    net_put_premium     NUMERIC,
    net_premium         NUMERIC,
    bullish_premium     NUMERIC,
    bearish_premium     NUMERIC,
    call_premium        NUMERIC,
    put_premium         NUMERIC,
    put_call_ratio      NUMERIC,
    iv_rank             NUMERIC,
    volatility          NUMERIC,
    iv30d               NUMERIC,
    implied_move        NUMERIC,
    implied_move_perc   NUMERIC,
    gex_net_change      NUMERIC,
    gex_ratio           NUMERIC,
    variance_risk_premium NUMERIC,
    total_open_interest BIGINT,
    relative_volume     NUMERIC,
    next_earnings_date  DATE,
    sector              TEXT,
    marketcap           NUMERIC,
    signals_present     TEXT[] NOT NULL DEFAULT '{}',
    confirmations       TEXT[] NOT NULL DEFAULT '{}',
    warnings            TEXT[] NOT NULL DEFAULT '{}',
    notes               TEXT,
    inserted_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, ticker)
);

COMMENT ON COLUMN uw_scan.scan_results.market_date         IS 'Trading date the screener row is dated to (UW `date` field).';
COMMENT ON COLUMN uw_scan.scan_results.next_earnings_date  IS 'Next scheduled earnings date for the underlying (UW screener).';
COMMENT ON COLUMN uw_scan.scan_results.inserted_at         IS 'Wall-clock time the row was written.';
