-- 109_theta_harvester.sql — Theta Harvester candidates + forward markouts.
-- Idempotent. No run_id FK by design: these are derived analytics that must
-- outlive scan_runs pruning (exposures_by_expiry_strike does NOT, which is why
-- net_gex/gex_flip are persisted as values here rather than re-derived later).

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.theta_harvester_candidates (
    ticker            TEXT NOT NULL,
    as_of             DATE NOT NULL,
    -- contract identity: re-markable from option_surface_grid_daily until expiry
    expiry            DATE NOT NULL,
    dte               INTEGER NOT NULL,
    put_strike        NUMERIC NOT NULL,
    call_strike       NUMERIC NOT NULL,
    -- entry state
    underlying_spot   NUMERIC NOT NULL,
    put_iv            NUMERIC NOT NULL,
    call_iv           NUMERIC NOT NULL,
    risk_free_rate    NUMERIC NOT NULL,
    -- entry mark (ALWAYS populated; the markout basis)
    put_mark          NUMERIC NOT NULL,
    call_mark         NUMERIC NOT NULL,
    entry_credit_theo NUMERIC NOT NULL,
    -- live IB quote (nullable; top-8-on-view only; slippage check, never the basis)
    credit_ib         NUMERIC,
    credit_quoted_at  TIMESTAMPTZ,
    credit_source     TEXT,
    -- structure greeks
    net_delta         NUMERIC NOT NULL,
    theta             NUMERIC NOT NULL,
    gamma             NUMERIC NOT NULL,
    vega              NUMERIC NOT NULL,
    -- signal
    score             NUMERIC NOT NULL,
    -- which ScoreWeights produced `score`. Re-scoring off the raw components
    -- below is always allowed; comparing stored scores across versions is not.
    weights_version   TEXT NOT NULL,
    verdict           TEXT NOT NULL,
    iv                NUMERIC,
    hv20              NUMERIC,
    hv60              NUMERIC,
    iv_rv_edge        NUMERIC,
    iv_rv_ratio       NUMERIC,
    trend_20d_pct     NUMERIC,
    range_score       NUMERIC,
    dealer_support    TEXT,
    net_gex           NUMERIC,
    gex_flip          NUMERIC,
    -- six gates, stored as columns so they are queryable without JSONB extraction
    gate_delta_near_zero  BOOLEAN NOT NULL,
    gate_iv_rich_vs_rv    BOOLEAN NOT NULL,
    gate_dealer_support   BOOLEAN NOT NULL,
    gate_theta_positive   BOOLEAN NOT NULL,
    gate_gamma_controlled BOOLEAN NOT NULL,
    gate_range_bound      BOOLEAN NOT NULL,
    inserted_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, as_of)
);

CREATE INDEX IF NOT EXISTS ix_theta_harvester_candidates_asof
  ON uw_scan.theta_harvester_candidates (as_of DESC, score DESC);

COMMENT ON TABLE uw_scan.theta_harvester_candidates IS
  'RESEARCH MEASUREMENT ARTIFACT, NOT A TRADE PROPOSAL. A short strangle is undefined-risk on both sides and violates argon''s no-naked-shorts rule; nothing sizes or routes from this table. One best short strangle per watchlist ticker per session, ranked from the warm store at zero UW cost. Rows of EVERY verdict are persisted deliberately — the non-THETA_HARVEST rows are the control arm, and short vol is positive-expectancy in most windows, so harvest-vs-zero is uninformative while harvest-vs-control is not. entry_credit_theo is the Black-Scholes mark from option_surface_grid_daily IV and is the ONLY valid markout basis; credit_ib is an opportunistic live NBBO for the top candidates, is selection-biased by which rows a human looked at, and must never be aggregated.';

CREATE TABLE IF NOT EXISTS uw_scan.theta_harvester_markouts (
    ticker         TEXT NOT NULL,
    as_of          DATE NOT NULL,
    horizon_days   INTEGER NOT NULL,
    mark_date      DATE NOT NULL,
    spot           NUMERIC,
    put_iv         NUMERIC,
    call_iv        NUMERIC,
    put_mark       NUMERIC,
    call_mark      NUMERIC,
    position_value NUMERIC,
    pnl            NUMERIC,
    pnl_pct_of_credit NUMERIC,
    breached       BOOLEAN,
    expired        BOOLEAN NOT NULL DEFAULT FALSE,
    inserted_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, as_of, horizon_days)
);

CREATE INDEX IF NOT EXISTS ix_theta_harvester_markouts_horizon
  ON uw_scan.theta_harvester_markouts (horizon_days, as_of DESC);

COMMENT ON TABLE uw_scan.theta_harvester_markouts IS
  'Forward re-marks of theta_harvester_candidates contracts, priced from option_surface_grid_daily on later dates. pnl is entry_credit_theo minus position_value (short strangle: positive = the credit was kept). horizon_days > 0 are intermediate marks and still carry time value; horizon_days = -1 is the TERMINAL at-expiry settlement mark, priced as intrinsic from daily_ohlc (the contract has left the option chain by then) and is the only row that observes the strategy''s realised risk. Aggregate the terminal row separately: averaging it together with intermediate horizons mixes two different quantities.';

COMMENT ON COLUMN uw_scan.theta_harvester_markouts.mark_date IS
  'The session actually priced, which may be later than as_of + horizon_days when the horizon lands on a weekend or a missed capture. Never the requested calendar date.';
