-- S1 core tables for the UW scanner. Idempotent. All multi-valued columns use TEXT[].
-- Every date/timestamp column carries a COMMENT ON COLUMN documenting its semantics.

CREATE SCHEMA IF NOT EXISTS uw_scan;

SET search_path TO uw_scan, public;

-- ----------------------------------------------------------------------------
-- scan_runs: one row per polling/snapshot run.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS uw_scan.scan_runs (
    run_id       BIGSERIAL PRIMARY KEY,
    ticker       TEXT      NOT NULL,
    started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at  TIMESTAMPTZ,
    status       TEXT      NOT NULL DEFAULT 'running',
    notes        TEXT
);

COMMENT ON COLUMN uw_scan.scan_runs.started_at  IS 'Wall-clock time the run started (DB now() at insert).';
COMMENT ON COLUMN uw_scan.scan_runs.finished_at IS 'Wall-clock time the run ended; NULL while in progress.';

-- ----------------------------------------------------------------------------
-- api_request_audit: one row per UW API call.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS uw_scan.api_request_audit (
    audit_id        BIGSERIAL PRIMARY KEY,
    run_id          BIGINT REFERENCES uw_scan.scan_runs(run_id) ON DELETE CASCADE,
    endpoint_slug   TEXT NOT NULL,
    endpoint_path   TEXT NOT NULL,
    params_json     JSONB NOT NULL DEFAULT '{}'::jsonb,
    status_code     INTEGER NOT NULL,
    request_started_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    request_finished_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    daily_req_count INTEGER,
    minute_req_remaining INTEGER,
    minute_req_reset TEXT,
    error_message   TEXT
);

COMMENT ON COLUMN uw_scan.api_request_audit.request_started_at  IS 'Wall-clock time request issued.';
COMMENT ON COLUMN uw_scan.api_request_audit.request_finished_at IS 'Wall-clock time response received.';

-- ----------------------------------------------------------------------------
-- raw_payloads: compressed JSON body, one per audit row.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS uw_scan.raw_payloads (
    payload_id   BIGSERIAL PRIMARY KEY,
    audit_id     BIGINT NOT NULL REFERENCES uw_scan.api_request_audit(audit_id) ON DELETE CASCADE,
    payload_jsonb JSONB NOT NULL,
    inserted_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON COLUMN uw_scan.raw_payloads.inserted_at IS 'Wall-clock time the row was written to the DB.';

-- ----------------------------------------------------------------------------
-- flow_events: normalized UW flow alert rows.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS uw_scan.flow_events (
    flow_event_id BIGSERIAL PRIMARY KEY,
    run_id        BIGINT NOT NULL REFERENCES uw_scan.scan_runs(run_id) ON DELETE CASCADE,
    alert_id      TEXT NOT NULL,
    ticker        TEXT NOT NULL,
    option_chain  TEXT,
    expiry        DATE,
    strike        NUMERIC,
    option_type   TEXT,
    price         NUMERIC,
    underlying_price NUMERIC,
    total_size    INTEGER,
    total_premium NUMERIC,
    total_ask_side_prem NUMERIC,
    total_bid_side_prem NUMERIC,
    volume        INTEGER,
    open_interest INTEGER,
    volume_oi_ratio NUMERIC,
    has_sweep     BOOLEAN,
    has_floor     BOOLEAN,
    has_multileg  BOOLEAN,
    all_opening_trades BOOLEAN,
    iv_start      NUMERIC,
    iv_end        NUMERIC,
    alert_rule    TEXT,
    rule_id       TEXT,
    sector        TEXT,
    issue_type    TEXT,
    next_earnings_date DATE,
    created_at    TIMESTAMPTZ,
    inserted_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (run_id, alert_id)
);

COMMENT ON COLUMN uw_scan.flow_events.expiry      IS 'Option expiry date.';
COMMENT ON COLUMN uw_scan.flow_events.created_at  IS 'UW-reported alert creation timestamp.';
COMMENT ON COLUMN uw_scan.flow_events.inserted_at IS 'Wall-clock time the row was written to the DB.';
COMMENT ON COLUMN uw_scan.flow_events.next_earnings_date IS 'Next scheduled earnings date for the underlying.';

-- ----------------------------------------------------------------------------
-- iv_rank_history: full IV rank time series.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS uw_scan.iv_rank_history (
    ticker      TEXT NOT NULL,
    market_date DATE NOT NULL,
    close       NUMERIC,
    volatility  NUMERIC,
    iv_rank_1y  NUMERIC,
    updated_at_src TIMESTAMPTZ,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, market_date)
);

COMMENT ON COLUMN uw_scan.iv_rank_history.market_date    IS 'Trading date the IV rank refers to.';
COMMENT ON COLUMN uw_scan.iv_rank_history.updated_at_src IS 'UW-reported updated_at for this daily row.';
COMMENT ON COLUMN uw_scan.iv_rank_history.inserted_at    IS 'Wall-clock time the row was written.';

-- ----------------------------------------------------------------------------
-- volatility_stats_history: full IV/RV stats time series.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS uw_scan.volatility_stats_history (
    ticker      TEXT NOT NULL,
    market_date DATE NOT NULL,
    iv          NUMERIC,
    iv_low      NUMERIC,
    iv_high     NUMERIC,
    iv_rank     NUMERIC,
    rv          NUMERIC,
    rv_low      NUMERIC,
    rv_high     NUMERIC,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, market_date)
);

COMMENT ON COLUMN uw_scan.volatility_stats_history.market_date IS 'Trading date the vol stats refer to.';
COMMENT ON COLUMN uw_scan.volatility_stats_history.inserted_at IS 'Wall-clock time the row was written.';

-- ----------------------------------------------------------------------------
-- realized_volatility_history: trailing RV time series.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS uw_scan.realized_volatility_history (
    ticker      TEXT NOT NULL,
    market_date DATE NOT NULL,
    price                NUMERIC,
    implied_volatility   NUMERIC,
    realized_volatility  NUMERIC,
    unshifted_rv_date    DATE,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, market_date)
);

COMMENT ON COLUMN uw_scan.realized_volatility_history.market_date       IS 'Trading date the RV row refers to.';
COMMENT ON COLUMN uw_scan.realized_volatility_history.unshifted_rv_date IS 'UW-reported unshifted RV reference date.';
COMMENT ON COLUMN uw_scan.realized_volatility_history.inserted_at       IS 'Wall-clock time the row was written.';

-- ----------------------------------------------------------------------------
-- iv_term_snapshots: term structure rows.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS uw_scan.iv_term_snapshots (
    run_id      BIGINT NOT NULL REFERENCES uw_scan.scan_runs(run_id) ON DELETE CASCADE,
    ticker      TEXT NOT NULL,
    market_date DATE NOT NULL,
    expiry      DATE NOT NULL,
    dte         INTEGER,
    volatility  NUMERIC,
    implied_move NUMERIC,
    implied_move_perc NUMERIC,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, ticker, expiry)
);

COMMENT ON COLUMN uw_scan.iv_term_snapshots.market_date IS 'Trading date the term row is dated to.';
COMMENT ON COLUMN uw_scan.iv_term_snapshots.expiry      IS 'Option expiry on the term curve.';
COMMENT ON COLUMN uw_scan.iv_term_snapshots.inserted_at IS 'Wall-clock time the row was written.';

-- ----------------------------------------------------------------------------
-- interpolated_iv_snapshots: standard tenor IV.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS uw_scan.interpolated_iv_snapshots (
    run_id      BIGINT NOT NULL REFERENCES uw_scan.scan_runs(run_id) ON DELETE CASCADE,
    ticker      TEXT NOT NULL,
    market_date DATE NOT NULL,
    days        INTEGER NOT NULL,
    percentile  NUMERIC,
    volatility  NUMERIC,
    implied_move_perc NUMERIC,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, ticker, days)
);

COMMENT ON COLUMN uw_scan.interpolated_iv_snapshots.market_date IS 'Trading date the interpolation refers to.';
COMMENT ON COLUMN uw_scan.interpolated_iv_snapshots.inserted_at IS 'Wall-clock time the row was written.';

-- ----------------------------------------------------------------------------
-- risk_reversal_skew_history: 25Δ (or other) skew time series.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS uw_scan.risk_reversal_skew_history (
    ticker      TEXT NOT NULL,
    market_date DATE NOT NULL,
    delta       INTEGER NOT NULL,
    expiry      DATE,
    risk_reversal NUMERIC,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, market_date, delta, expiry)
);

COMMENT ON COLUMN uw_scan.risk_reversal_skew_history.market_date IS 'Trading date the skew row is dated to.';
COMMENT ON COLUMN uw_scan.risk_reversal_skew_history.expiry      IS 'Expiry used for the skew query.';
COMMENT ON COLUMN uw_scan.risk_reversal_skew_history.inserted_at IS 'Wall-clock time the row was written.';

-- ----------------------------------------------------------------------------
-- greeks_by_expiry_strike: per-(expiry, strike) call/put greeks.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS uw_scan.greeks_by_expiry_strike (
    run_id      BIGINT NOT NULL REFERENCES uw_scan.scan_runs(run_id) ON DELETE CASCADE,
    ticker      TEXT NOT NULL,
    market_date DATE NOT NULL,
    expiry      DATE NOT NULL,
    strike      NUMERIC NOT NULL,
    call_delta  NUMERIC,
    put_delta   NUMERIC,
    call_gamma  NUMERIC,
    put_gamma   NUMERIC,
    call_vega   NUMERIC,
    put_vega    NUMERIC,
    call_theta  NUMERIC,
    put_theta   NUMERIC,
    call_rho    NUMERIC,
    put_rho     NUMERIC,
    call_vanna  NUMERIC,
    put_vanna   NUMERIC,
    call_charm  NUMERIC,
    put_charm   NUMERIC,
    call_volatility NUMERIC,
    put_volatility  NUMERIC,
    call_option_symbol TEXT,
    put_option_symbol  TEXT,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, ticker, expiry, strike)
);

COMMENT ON COLUMN uw_scan.greeks_by_expiry_strike.market_date IS 'Trading date the greeks refer to.';
COMMENT ON COLUMN uw_scan.greeks_by_expiry_strike.expiry      IS 'Option expiry.';
COMMENT ON COLUMN uw_scan.greeks_by_expiry_strike.inserted_at IS 'Wall-clock time the row was written.';

-- ----------------------------------------------------------------------------
-- exposures_by_expiry_strike: GEX/DEX/vanna/charm exposures.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS uw_scan.exposures_by_expiry_strike (
    run_id      BIGINT NOT NULL REFERENCES uw_scan.scan_runs(run_id) ON DELETE CASCADE,
    ticker      TEXT NOT NULL,
    market_date DATE NOT NULL,
    expiry      DATE NOT NULL,
    strike      NUMERIC NOT NULL,
    dte         INTEGER,
    call_delta  NUMERIC,
    put_delta   NUMERIC,
    call_gex    NUMERIC,
    put_gex     NUMERIC,
    call_vanna  NUMERIC,
    put_vanna   NUMERIC,
    call_charm  NUMERIC,
    put_charm   NUMERIC,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, ticker, expiry, strike)
);

COMMENT ON COLUMN uw_scan.exposures_by_expiry_strike.market_date IS 'Trading date the exposures refer to.';
COMMENT ON COLUMN uw_scan.exposures_by_expiry_strike.expiry      IS 'Option expiry.';
COMMENT ON COLUMN uw_scan.exposures_by_expiry_strike.inserted_at IS 'Wall-clock time the row was written.';

-- ----------------------------------------------------------------------------
-- oi_by_strike: per-strike OI (date-keyed).
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS uw_scan.oi_by_strike (
    ticker      TEXT NOT NULL,
    market_date DATE NOT NULL,
    strike      NUMERIC NOT NULL,
    call_oi     BIGINT,
    put_oi      BIGINT,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, market_date, strike)
);

COMMENT ON COLUMN uw_scan.oi_by_strike.market_date IS 'Trading date the OI snapshot refers to.';
COMMENT ON COLUMN uw_scan.oi_by_strike.inserted_at IS 'Wall-clock time the row was written.';

-- ----------------------------------------------------------------------------
-- oi_change_events: contract-level OI deltas (top movers).
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS uw_scan.oi_change_events (
    run_id          BIGINT NOT NULL REFERENCES uw_scan.scan_runs(run_id) ON DELETE CASCADE,
    underlying_symbol TEXT NOT NULL,
    option_symbol   TEXT NOT NULL,
    curr_date       DATE,
    last_date       DATE,
    curr_oi         BIGINT,
    last_oi         BIGINT,
    oi_diff_plain   BIGINT,
    oi_change       NUMERIC,
    volume          BIGINT,
    trades          INTEGER,
    avg_price       NUMERIC,
    last_fill       NUMERIC,
    days_of_oi_increases INTEGER,
    days_of_vol_greater_than_oi INTEGER,
    percentage_of_total NUMERIC,
    rnk             INTEGER,
    inserted_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, option_symbol)
);

COMMENT ON COLUMN uw_scan.oi_change_events.curr_date   IS 'Current trading date for the OI delta row.';
COMMENT ON COLUMN uw_scan.oi_change_events.last_date   IS 'Previous trading date used as baseline.';
COMMENT ON COLUMN uw_scan.oi_change_events.inserted_at IS 'Wall-clock time the row was written.';

-- ----------------------------------------------------------------------------
-- max_pain_by_expiry: per-expiry max pain snapshots.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS uw_scan.max_pain_by_expiry (
    run_id      BIGINT NOT NULL REFERENCES uw_scan.scan_runs(run_id) ON DELETE CASCADE,
    ticker      TEXT NOT NULL,
    market_date DATE NOT NULL,
    expiry      DATE NOT NULL,
    max_pain    NUMERIC,
    close       NUMERIC,
    open        NUMERIC,
    next_upper_strike NUMERIC,
    next_lower_strike NUMERIC,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, ticker, expiry)
);

COMMENT ON COLUMN uw_scan.max_pain_by_expiry.market_date IS 'Trading date the max pain refers to.';
COMMENT ON COLUMN uw_scan.max_pain_by_expiry.expiry      IS 'Option expiry.';
COMMENT ON COLUMN uw_scan.max_pain_by_expiry.inserted_at IS 'Wall-clock time the row was written.';

-- ----------------------------------------------------------------------------
-- option_contract_snapshots: per-contract snapshot.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS uw_scan.option_contract_snapshots (
    run_id          BIGINT NOT NULL REFERENCES uw_scan.scan_runs(run_id) ON DELETE CASCADE,
    ticker          TEXT NOT NULL,
    option_symbol   TEXT NOT NULL,
    last_price      NUMERIC,
    nbbo_bid        NUMERIC,
    nbbo_ask        NUMERIC,
    implied_volatility NUMERIC,
    open_interest   BIGINT,
    prev_oi         BIGINT,
    volume          BIGINT,
    ask_volume      BIGINT,
    bid_volume      BIGINT,
    mid_volume      BIGINT,
    multi_leg_volume BIGINT,
    stock_multi_leg_volume BIGINT,
    floor_volume    BIGINT,
    sweep_volume    BIGINT,
    no_side_volume  BIGINT,
    avg_price       NUMERIC,
    high_price      NUMERIC,
    low_price       NUMERIC,
    total_premium   NUMERIC,
    inserted_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, option_symbol)
);

COMMENT ON COLUMN uw_scan.option_contract_snapshots.inserted_at IS 'Wall-clock time the row was written.';

-- ----------------------------------------------------------------------------
-- dark_pool_events: dark pool prints.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS uw_scan.dark_pool_events (
    run_id          BIGINT NOT NULL REFERENCES uw_scan.scan_runs(run_id) ON DELETE CASCADE,
    ticker          TEXT NOT NULL,
    tracking_id     BIGINT NOT NULL,
    executed_at     TIMESTAMPTZ,
    trf_executed_at TIMESTAMPTZ,
    price           NUMERIC,
    size            BIGINT,
    premium         NUMERIC,
    nbbo_bid        NUMERIC,
    nbbo_ask        NUMERIC,
    nbbo_bid_quantity BIGINT,
    nbbo_ask_quantity BIGINT,
    market_center   TEXT,
    sale_cond_codes TEXT,
    ext_hour_sold_codes TEXT,
    trade_code      TEXT,
    trade_settlement TEXT,
    canceled        BOOLEAN,
    inserted_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, tracking_id)
);

COMMENT ON COLUMN uw_scan.dark_pool_events.executed_at     IS 'UW-reported execution timestamp of the print.';
COMMENT ON COLUMN uw_scan.dark_pool_events.trf_executed_at IS 'UW-reported TRF execution timestamp.';
COMMENT ON COLUMN uw_scan.dark_pool_events.inserted_at     IS 'Wall-clock time the row was written.';

-- ----------------------------------------------------------------------------
-- short_interest_snapshots: latest short_data row per run.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS uw_scan.short_interest_snapshots (
    run_id      BIGINT NOT NULL PRIMARY KEY REFERENCES uw_scan.scan_runs(run_id) ON DELETE CASCADE,
    ticker      TEXT NOT NULL,
    name        TEXT,
    snapshot_at TIMESTAMPTZ,
    short_shares_available BIGINT,
    fee_rate    NUMERIC,
    rebate_rate NUMERIC,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON COLUMN uw_scan.short_interest_snapshots.snapshot_at IS 'UW-reported timestamp of the snapshot.';
COMMENT ON COLUMN uw_scan.short_interest_snapshots.inserted_at IS 'Wall-clock time the row was written.';

-- ----------------------------------------------------------------------------
-- opportunity_scores: conviction score + setup types.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS uw_scan.opportunity_scores (
    score_id    BIGSERIAL PRIMARY KEY,
    run_id      BIGINT NOT NULL REFERENCES uw_scan.scan_runs(run_id) ON DELETE CASCADE,
    ticker      TEXT NOT NULL,
    score       NUMERIC NOT NULL,
    setup_types TEXT[] NOT NULL DEFAULT '{}',
    direction   TEXT,
    confirmations TEXT[] NOT NULL DEFAULT '{}',
    warnings    TEXT[] NOT NULL DEFAULT '{}',
    notes       TEXT,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON COLUMN uw_scan.opportunity_scores.inserted_at IS 'Wall-clock time the row was written.';

-- ----------------------------------------------------------------------------
-- structure_ideas: suggested structures for opportunities.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS uw_scan.structure_ideas (
    idea_id     BIGSERIAL PRIMARY KEY,
    run_id      BIGINT NOT NULL REFERENCES uw_scan.scan_runs(run_id) ON DELETE CASCADE,
    ticker      TEXT NOT NULL,
    structure   TEXT NOT NULL,
    legs_json   JSONB NOT NULL DEFAULT '[]'::jsonb,
    rationale   TEXT,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON COLUMN uw_scan.structure_ideas.inserted_at IS 'Wall-clock time the row was written.';

-- ----------------------------------------------------------------------------
-- Deferred-to-S6 tables (declared empty here so the schema is complete).
-- Row counts in S1 exit gate assert these have 0 rows.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS uw_scan.option_surface_snapshots (
    surface_id  BIGSERIAL PRIMARY KEY,
    run_id      BIGINT NOT NULL REFERENCES uw_scan.scan_runs(run_id) ON DELETE CASCADE,
    ticker      TEXT NOT NULL,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON COLUMN uw_scan.option_surface_snapshots.inserted_at IS 'Wall-clock time the row was written. (S6 deferred.)';

CREATE TABLE IF NOT EXISTS uw_scan.oi_by_expiry (
    ticker      TEXT NOT NULL,
    market_date DATE NOT NULL,
    expiry      DATE NOT NULL,
    call_oi     BIGINT,
    put_oi      BIGINT,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, market_date, expiry)
);

COMMENT ON COLUMN uw_scan.oi_by_expiry.market_date IS 'Trading date. (S6 deferred.)';
COMMENT ON COLUMN uw_scan.oi_by_expiry.expiry      IS 'Option expiry. (S6 deferred.)';
COMMENT ON COLUMN uw_scan.oi_by_expiry.inserted_at IS 'Wall-clock time the row was written. (S6 deferred.)';
