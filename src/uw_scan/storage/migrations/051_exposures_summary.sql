-- 051_exposures_summary.sql
-- Per-(expiry) derived summary used by the Vanna/Charm sub-tabs.
-- One row per (run_id, ticker, expiry) — primary key. Idempotent.
--
-- run_id is BIGINT with FK ON DELETE CASCADE to match the convention used by
-- every other run-keyed table in migration 001 (scan_runs.run_id is BIGSERIAL;
-- INTEGER would overflow on long-running deployments and an orphan summary
-- after scan-runs cleanup would be a data-integrity papercut).

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.exposures_summary (
    run_id               BIGINT  NOT NULL
                                 REFERENCES uw_scan.scan_runs(run_id) ON DELETE CASCADE,
    ticker               TEXT    NOT NULL,
    expiry               DATE    NOT NULL,
    market_date          DATE    NOT NULL,
    dte                  INTEGER,
    spot                 NUMERIC,

    -- Vanna ---
    net_vanna            NUMERIC,
    top_vanna_strike     NUMERIC,
    top_vanna_value      NUMERIC,
    delta_shock_1pt_iv   NUMERIC,
    vanna_regime         TEXT,
    vanna_flip           NUMERIC,
    vanna_headline       TEXT,
    vanna_subtitle       TEXT,

    -- Charm ---
    net_charm            NUMERIC,
    charm_pin_strike     NUMERIC,
    charm_above_sum      NUMERIC,
    charm_below_sum      NUMERIC,
    charm_imbalance_pct  NUMERIC,
    charm_signal_quality TEXT,
    charm_flip           NUMERIC,
    charm_headline       TEXT,
    charm_subtitle       TEXT,

    computed_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (run_id, ticker, expiry)
);

CREATE INDEX IF NOT EXISTS exposures_summary_ticker_date_idx
    ON uw_scan.exposures_summary (ticker, market_date);
