CREATE TABLE IF NOT EXISTS uw_scan.flow_events (
    flow_event_id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES uw_scan.scan_runs(run_id),
    ticker TEXT NOT NULL,
    option_symbol TEXT NOT NULL,
    expiry DATE,
    strike NUMERIC,
    option_type TEXT,
    dte INTEGER,
    event_timestamp_utc TIMESTAMPTZ,
    fetched_at_utc TIMESTAMPTZ NOT NULL,
    market_date DATE NOT NULL,
    side TEXT,
    premium NUMERIC,
    volume INTEGER,
    open_interest INTEGER,
    ask_side_pct NUMERIC,
    UNIQUE (run_id, option_symbol, event_timestamp_utc, premium, volume)
);

ALTER TABLE uw_scan.flow_events ADD COLUMN IF NOT EXISTS expiry DATE;
ALTER TABLE uw_scan.flow_events ADD COLUMN IF NOT EXISTS strike NUMERIC;
ALTER TABLE uw_scan.flow_events ADD COLUMN IF NOT EXISTS option_type TEXT;
ALTER TABLE uw_scan.flow_events ADD COLUMN IF NOT EXISTS dte INTEGER;

CREATE TABLE IF NOT EXISTS uw_scan.option_surface_snapshots (
    option_surface_snapshot_id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES uw_scan.scan_runs(run_id),
    ticker TEXT NOT NULL,
    market_date DATE NOT NULL,
    fetched_at_utc TIMESTAMPTZ NOT NULL,
    expiry DATE NOT NULL,
    page_number INTEGER NOT NULL,
    row_count INTEGER NOT NULL,
    complete BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE (run_id, ticker, market_date, expiry, page_number)
);

CREATE TABLE IF NOT EXISTS uw_scan.exposures_by_expiry_strike (
    exposure_row_id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES uw_scan.scan_runs(run_id),
    ticker TEXT NOT NULL,
    market_date DATE NOT NULL,
    fetched_at_utc TIMESTAMPTZ NOT NULL,
    expiry DATE NOT NULL,
    strike NUMERIC NOT NULL,
    delta_exposure NUMERIC,
    gamma_exposure NUMERIC,
    vanna_exposure NUMERIC,
    charm_exposure NUMERIC,
    UNIQUE (run_id, ticker, market_date, expiry, strike)
);

CREATE TABLE IF NOT EXISTS uw_scan.oi_by_strike (
    oi_by_strike_id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES uw_scan.scan_runs(run_id),
    ticker TEXT NOT NULL,
    market_date DATE NOT NULL,
    fetched_at_utc TIMESTAMPTZ NOT NULL,
    strike NUMERIC NOT NULL,
    call_open_interest INTEGER,
    put_open_interest INTEGER,
    UNIQUE (run_id, ticker, market_date, strike)
);

CREATE TABLE IF NOT EXISTS uw_scan.oi_change_events (
    oi_change_event_id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES uw_scan.scan_runs(run_id),
    option_symbol TEXT NOT NULL,
    ticker TEXT NOT NULL,
    oi_change_date DATE NOT NULL,
    open_interest INTEGER,
    previous_open_interest INTEGER,
    open_interest_change INTEGER,
    UNIQUE (run_id, option_symbol, oi_change_date)
);

CREATE TABLE IF NOT EXISTS uw_scan.iv_rank_history (
    iv_rank_history_id BIGSERIAL PRIMARY KEY,
    ticker TEXT NOT NULL,
    market_date DATE NOT NULL,
    iv_rank NUMERIC,
    implied_volatility NUMERIC,
    realized_volatility NUMERIC,
    UNIQUE (ticker, market_date)
);

CREATE TABLE IF NOT EXISTS uw_scan.iv_term_snapshots (
    iv_term_snapshot_id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES uw_scan.scan_runs(run_id),
    ticker TEXT NOT NULL,
    market_date DATE NOT NULL,
    fetched_at_utc TIMESTAMPTZ NOT NULL,
    expiry DATE NOT NULL,
    dte INTEGER,
    implied_volatility NUMERIC,
    implied_move NUMERIC,
    UNIQUE (run_id, ticker, market_date, expiry)
);

CREATE TABLE IF NOT EXISTS uw_scan.interpolated_iv_snapshots (
    interpolated_iv_snapshot_id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES uw_scan.scan_runs(run_id),
    ticker TEXT NOT NULL,
    market_date DATE NOT NULL,
    fetched_at_utc TIMESTAMPTZ NOT NULL,
    dte_bucket INTEGER NOT NULL,
    implied_volatility NUMERIC,
    percentile NUMERIC,
    implied_move NUMERIC,
    UNIQUE (run_id, ticker, market_date, dte_bucket)
);

CREATE TABLE IF NOT EXISTS uw_scan.realized_volatility_history (
    realized_volatility_history_id BIGSERIAL PRIMARY KEY,
    ticker TEXT NOT NULL,
    market_date DATE NOT NULL,
    vol_window TEXT NOT NULL,
    realized_volatility NUMERIC,
    underlying_price NUMERIC,
    UNIQUE (ticker, market_date, vol_window)
);

CREATE TABLE IF NOT EXISTS uw_scan.risk_reversal_skew_history (
    risk_reversal_skew_history_id BIGSERIAL PRIMARY KEY,
    ticker TEXT NOT NULL,
    market_date DATE NOT NULL,
    expiry DATE NOT NULL,
    delta NUMERIC NOT NULL,
    put_volatility NUMERIC,
    call_volatility NUMERIC,
    skew_magnitude NUMERIC,
    UNIQUE (ticker, market_date, expiry, delta)
);

CREATE TABLE IF NOT EXISTS uw_scan.max_pain_by_expiry (
    max_pain_by_expiry_id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES uw_scan.scan_runs(run_id),
    ticker TEXT NOT NULL,
    market_date DATE NOT NULL,
    fetched_at_utc TIMESTAMPTZ NOT NULL,
    expiry DATE NOT NULL,
    max_pain NUMERIC,
    spot_price NUMERIC,
    UNIQUE (run_id, ticker, market_date, expiry)
);

CREATE TABLE IF NOT EXISTS uw_scan.dark_pool_events (
    dark_pool_event_id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES uw_scan.scan_runs(run_id),
    ticker TEXT NOT NULL,
    market_date DATE NOT NULL,
    event_timestamp_utc TIMESTAMPTZ,
    price NUMERIC,
    premium NUMERIC,
    size INTEGER,
    venue TEXT
);

CREATE TABLE IF NOT EXISTS uw_scan.short_interest_snapshots (
    short_interest_snapshot_id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES uw_scan.scan_runs(run_id),
    ticker TEXT NOT NULL,
    market_date DATE NOT NULL,
    fetched_at_utc TIMESTAMPTZ NOT NULL,
    short_interest_pct_float NUMERIC,
    utilization NUMERIC,
    days_to_cover NUMERIC,
    cost_to_borrow NUMERIC,
    UNIQUE (run_id, ticker, market_date)
);

CREATE TABLE IF NOT EXISTS uw_scan.tracked_items (
    tracked_item_id BIGSERIAL PRIMARY KEY,
    ticker TEXT NOT NULL,
    option_symbol TEXT,
    expiry DATE,
    tracking_kind TEXT NOT NULL,
    source_run_id TEXT REFERENCES uw_scan.scan_runs(run_id),
    created_at_utc TIMESTAMPTZ NOT NULL DEFAULT now(),
    active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS uw_scan.tracking_observations (
    tracking_observation_id BIGSERIAL PRIMARY KEY,
    tracked_item_id BIGINT NOT NULL REFERENCES uw_scan.tracked_items(tracked_item_id),
    observed_at_utc TIMESTAMPTZ NOT NULL,
    metric_family TEXT NOT NULL,
    iv_change NUMERIC,
    oi_change INTEGER,
    reconciliation_status TEXT,
    UNIQUE (tracked_item_id, observed_at_utc, metric_family)
);

CREATE TABLE IF NOT EXISTS uw_scan.structure_ideas (
    structure_idea_id BIGSERIAL PRIMARY KEY,
    opportunity_score_id BIGINT NOT NULL REFERENCES uw_scan.opportunity_scores(opportunity_score_id),
    structure_type TEXT NOT NULL,
    rationale TEXT NOT NULL,
    invalidation TEXT NOT NULL,
    max_risk_note TEXT NOT NULL DEFAULT 'Sizing deferred',
    UNIQUE (opportunity_score_id, structure_type)
);

INSERT INTO uw_scan.schema_versions (version)
VALUES ('002_expand_v1_tables')
ON CONFLICT (version) DO NOTHING;
