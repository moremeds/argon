-- 081_vrp_trading.sql
-- VRP tradable iron-condor layer: per-ticker candidates, model-repriced backtest
-- (results + per-trade detail), paper ledger, and forward true-fill NBBO capture.
-- Flat-vol pricing (skew ignored) — see plan. Idempotent.
-- Design: docs/superpowers/plans/2026-06-22-vrp-tradable-condor-backtest.md
SET search_path TO uw_scan, public;

BEGIN;

CREATE TABLE IF NOT EXISTS uw_scan.vrp_trade_candidates (
    ticker          TEXT NOT NULL,
    as_of           DATE NOT NULL,
    structure       TEXT NOT NULL DEFAULT 'iron_condor',
    spot            NUMERIC,
    iv              NUMERIC,
    vrp_z           NUMERIC,
    hold_days       INTEGER NOT NULL,
    short_put       NUMERIC, long_put  NUMERIC,
    short_call      NUMERIC, long_call NUMERIC,
    entry_credit    NUMERIC, max_loss  NUMERIC,
    put_width       NUMERIC, call_width NUMERIC,
    entry_cost      NUMERIC,                 -- modeled round-trip cost (CostModel) carried to the paper ledger
    bucket_sector   TEXT,
    bucket_verdict  TEXT,
    earnings_clear  BOOLEAN NOT NULL DEFAULT TRUE,
    contracts       INTEGER NOT NULL DEFAULT 1,
    inserted_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, as_of)
);
COMMENT ON TABLE uw_scan.vrp_trade_candidates IS
    'Daily per-ticker iron-condor candidates (RICH × SELLABLE-bucket × earnings-clear). Flat-vol modeled credit.';

CREATE TABLE IF NOT EXISTS uw_scan.vrp_backtest_results (
    unit_type            TEXT NOT NULL,   -- 'ticker' | 'bucket'
    unit_key             TEXT NOT NULL,   -- ticker symbol | sector name
    hold_days            INTEGER NOT NULL,
    scope                TEXT NOT NULL,   -- 'full' | 'holdout'
    n_trades             INTEGER NOT NULL DEFAULT 0,
    n_wins               INTEGER NOT NULL DEFAULT 0,
    win_rate             NUMERIC,
    mean_net             NUMERIC,
    median_net           NUMERIC,
    total_net            NUMERIC,
    mean_return_on_risk  NUMERIC,
    breach_rate          NUMERIC,   -- fraction of trades that breached a SHORT strike (entered loss zone)
    mean_credit          NUMERIC,
    as_of                DATE,
    inserted_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (unit_type, unit_key, hold_days, scope)
);
COMMENT ON TABLE uw_scan.vrp_backtest_results IS
    'Model-repriced condor backtest summary per unit. scope=full is characterization; scope=holdout (latest 40%) is the honest headline.';

CREATE TABLE IF NOT EXISTS uw_scan.vrp_backtest_trades (
    ticker          TEXT NOT NULL,
    entry_date      DATE NOT NULL,
    hold_days       INTEGER NOT NULL,
    expiry_date     DATE,
    spot_entry      NUMERIC, spot_exit NUMERIC, iv_entry NUMERIC,
    entry_credit    NUMERIC, max_loss  NUMERIC,
    gross_pnl       NUMERIC, net_pnl   NUMERIC,
    return_on_risk  NUMERIC,
    breached        BOOLEAN,
    in_holdout      BOOLEAN NOT NULL DEFAULT FALSE,
    inserted_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, entry_date, hold_days)
);
COMMENT ON TABLE uw_scan.vrp_backtest_trades IS
    'Per-trade detail backing vrp_backtest_results (audit + holdout flag).';

CREATE TABLE IF NOT EXISTS uw_scan.vrp_paper_positions (
    position_id     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ticker          TEXT NOT NULL,
    opened_on       DATE NOT NULL,
    hold_days       INTEGER NOT NULL,
    expiry_on       DATE NOT NULL,
    short_put       NUMERIC, long_put  NUMERIC,
    short_call      NUMERIC, long_call NUMERIC,
    entry_credit    NUMERIC, max_loss  NUMERIC,
    entry_cost      NUMERIC,                 -- modeled round-trip cost; netted into realized/unrealized P&L
    contracts       INTEGER NOT NULL DEFAULT 1,
    spot_entry      NUMERIC, iv_entry  NUMERIC,
    status          TEXT NOT NULL DEFAULT 'open',  -- 'open' | 'closed'
    last_mark_on    DATE,
    mark_value      NUMERIC,
    unrealized_pnl  NUMERIC,
    closed_on       DATE,
    exit_value      NUMERIC,
    realized_pnl    NUMERIC,
    mark_source     TEXT NOT NULL DEFAULT 'model', -- 'model' | 'nbbo'
    inserted_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (ticker, opened_on)  -- one paper position per candidate per day (idempotent open)
);
COMMENT ON TABLE uw_scan.vrp_paper_positions IS
    'Simulated iron-condor positions: open → daily model mark → close at expiry (realized payoff vs adjusted price).';

CREATE TABLE IF NOT EXISTS uw_scan.vrp_leg_nbbo (
    position_id     BIGINT NOT NULL REFERENCES uw_scan.vrp_paper_positions(position_id) ON DELETE CASCADE,
    leg             TEXT NOT NULL,   -- short_put | long_put | short_call | long_call
    capture_date    DATE NOT NULL,
    strike          NUMERIC,
    expiry          DATE,
    option_symbol   TEXT,
    nbbo_bid        NUMERIC, nbbo_ask NUMERIC, last_price NUMERIC, iv NUMERIC,
    inserted_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (position_id, leg, capture_date)
);
COMMENT ON TABLE uw_scan.vrp_leg_nbbo IS
    'Forward real NBBO per candidate leg — the true-fill dataset to later calibrate model credit error. No consumer yet.';

COMMIT;
