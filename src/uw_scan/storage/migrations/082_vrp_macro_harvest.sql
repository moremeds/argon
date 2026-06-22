-- Macro systematic short-vol harvest sweep results.
-- Which defined-risk structure (condor / bull put spread / cash-secured put) at
-- which gate × short-delta × horizon converts the macro VRP into positive
-- risk-adjusted P&L. Research output; full-rewrite per run. Idempotent.
SET search_path TO uw_scan, public;
BEGIN;

CREATE TABLE IF NOT EXISTS uw_scan.vrp_macro_sweep_results (
    ticker               TEXT NOT NULL,
    structure            TEXT NOT NULL,   -- iron_condor | bull_put_spread | cash_secured_put
    gate                 TEXT NOT NULL,   -- always_on | z>=0 | z>=0.5 | z>=1.0
    short_delta          NUMERIC NOT NULL,
    hold_days            INTEGER NOT NULL,
    scope                TEXT NOT NULL,   -- full | holdout
    n_trades             INTEGER NOT NULL DEFAULT 0,
    n_wins               INTEGER NOT NULL DEFAULT 0,
    win_rate             NUMERIC,
    total_net            NUMERIC,
    mean_net             NUMERIC,
    median_net           NUMERIC,
    mean_return_on_risk  NUMERIC,
    breakeven_win_rate   NUMERIC,         -- win-rate the structure needs to clear ROR=0
    breach_rate          NUMERIC,
    mean_credit          NUMERIC,
    as_of                DATE,
    inserted_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, structure, gate, short_delta, hold_days, scope)
);

COMMENT ON TABLE uw_scan.vrp_macro_sweep_results IS
    'Macro short-vol sweep: structure x gate x short-delta x horizon, entry-spaced, full+holdout. Research output — does any defined-risk structure harvest the macro VRP at positive risk-adjusted P&L.';

COMMIT;
