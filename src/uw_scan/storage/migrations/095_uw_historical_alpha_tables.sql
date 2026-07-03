-- 095_uw_historical_alpha_tables.sql
-- Durable UW historical alpha datasets for 1-3 week US-stock swing research.
-- Idempotent. Tables are intentionally independent of scan_runs so research
-- history is not cascade-deleted with transient scanner runs.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_volatility_signal_daily (
    ticker              TEXT NOT NULL,
    market_date         DATE NOT NULL,
    anomaly_direction   TEXT,
    anomaly_score       NUMERIC,
    vol_character       TEXT,
    half_life_days      NUMERIC,
    hurst_rv            NUMERIC,
    vrp_rank            NUMERIC,
    risk_premium        NUMERIC,
    source_mask         TEXT[] NOT NULL DEFAULT '{}',
    raw_jsonb           JSONB,
    fetched_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, market_date)
);

CREATE INDEX IF NOT EXISTS ix_uw_vol_signal_date
    ON uw_volatility_signal_daily (market_date DESC, ticker);

CREATE TABLE IF NOT EXISTS uw_gex_levels_daily (
    ticker          TEXT NOT NULL,
    market_date     DATE NOT NULL,
    call_wall       NUMERIC,
    put_wall        NUMERIC,
    gamma_flip      NUMERIC,
    gamma_magnet    NUMERIC,
    spot            NUMERIC,
    raw_jsonb       JSONB,
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, market_date)
);

CREATE INDEX IF NOT EXISTS ix_uw_gex_levels_date
    ON uw_gex_levels_daily (market_date DESC, ticker);

CREATE TABLE IF NOT EXISTS uw_intraday_option_flow_bars (
    ticker              TEXT NOT NULL,
    market_date         DATE NOT NULL,
    ts                  TIMESTAMPTZ NOT NULL,
    source              TEXT NOT NULL,
    expiry              DATE NOT NULL DEFAULT '0001-01-01',
    net_call_premium    NUMERIC,
    net_put_premium     NUMERIC,
    net_delta           NUMERIC,
    call_volume         BIGINT,
    put_volume          BIGINT,
    dir_delta_flow      NUMERIC,
    dir_vega_flow       NUMERIC,
    otm_dir_delta_flow  NUMERIC,
    otm_dir_vega_flow   NUMERIC,
    transactions        BIGINT,
    volume              BIGINT,
    raw_jsonb           JSONB,
    fetched_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, market_date, ts, source, expiry)
);

CREATE INDEX IF NOT EXISTS ix_uw_intraday_flow_date
    ON uw_intraday_option_flow_bars (market_date DESC, ticker, source);

CREATE TABLE IF NOT EXISTS uw_dark_lit_flow_prints (
    source              TEXT NOT NULL,
    tracking_id         TEXT NOT NULL,
    ticker              TEXT NOT NULL,
    executed_at         TIMESTAMPTZ NOT NULL,
    market_date         DATE NOT NULL,
    price               NUMERIC,
    size                BIGINT,
    premium             NUMERIC,
    market_center       TEXT,
    nbbo_bid            NUMERIC,
    nbbo_ask            NUMERIC,
    nbbo_bid_quantity   BIGINT,
    nbbo_ask_quantity   BIGINT,
    sale_cond_codes     TEXT[],
    trade_code          TEXT,
    raw_jsonb           JSONB,
    fetched_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (source, tracking_id)
);

CREATE INDEX IF NOT EXISTS ix_uw_dark_lit_date_ticker
    ON uw_dark_lit_flow_prints (market_date DESC, ticker, source);

CREATE TABLE IF NOT EXISTS uw_short_pressure_daily (
    ticker                                      TEXT NOT NULL,
    market_date                                 DATE NOT NULL,
    short_interest                              NUMERIC,
    si_float                                    NUMERIC,
    si_float_with_synth_long_pct_of_total_shares NUMERIC,
    days_to_cover                               NUMERIC,
    fee_rate                                    NUMERIC,
    rebate_rate                                 NUMERIC,
    short_shares_available                      NUMERIC,
    total_float                                 NUMERIC,
    ftd_quantity                                NUMERIC,
    short_volume                                NUMERIC,
    total_volume                                NUMERIC,
    short_volume_ratio                          NUMERIC,
    raw_jsonb                                   JSONB,
    fetched_at                                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, market_date)
);

CREATE INDEX IF NOT EXISTS ix_uw_short_pressure_date
    ON uw_short_pressure_daily (market_date DESC, ticker);
