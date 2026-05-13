-- 015_flow_tab_merge.sql
-- Adds the two new tables that back the merged Flow tab + extends oi_change_events
-- with the aggressor/premium breakdown UW provides on the oi-change payload.

BEGIN;

-- ---------------------------------------------------------------------------
-- options_volume_daily: 180-day daily series of total options volume + OI,
-- ask/bid aggressor splits, bullish/bearish premium, built-in 3/7/30-day averages.
-- Source: UW /api/stock/{ticker}/options-volume
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS uw_scan.options_volume_daily (
    ticker                  TEXT         NOT NULL,
    trade_date              DATE         NOT NULL,
    call_volume             BIGINT,
    put_volume              BIGINT,
    call_volume_ask_side    BIGINT,
    call_volume_bid_side    BIGINT,
    put_volume_ask_side     BIGINT,
    put_volume_bid_side     BIGINT,
    call_premium            NUMERIC(20, 4),
    put_premium             NUMERIC(20, 4),
    net_call_premium        NUMERIC(20, 4),
    net_put_premium         NUMERIC(20, 4),
    bullish_premium         NUMERIC(20, 4),
    bearish_premium         NUMERIC(20, 4),
    call_open_interest      BIGINT,
    put_open_interest       BIGINT,
    avg_3_day_call_volume   NUMERIC(14, 4),
    avg_3_day_put_volume    NUMERIC(14, 4),
    avg_7_day_call_volume   NUMERIC(14, 4),
    avg_7_day_put_volume    NUMERIC(14, 4),
    avg_30_day_call_volume  NUMERIC(14, 4),
    avg_30_day_put_volume   NUMERIC(14, 4),
    fetched_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, trade_date)
);
CREATE INDEX IF NOT EXISTS idx_ovd_ticker_date
    ON uw_scan.options_volume_daily(ticker, trade_date DESC);

-- ---------------------------------------------------------------------------
-- option_chain_per_strike: per-(expiry, strike) volume + OI snapshot.
-- Source: aggregation of UW /api/stock/{ticker}/option-contracts payload
-- (existing oi_by_strike has no expiry column and cannot feed the per-expiry
--  profile chart; this new table backs BOTH the volume and OI strike profiles).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS uw_scan.option_chain_per_strike (
    ticker        TEXT      NOT NULL,
    snapshot_date DATE      NOT NULL,
    expiry        DATE      NOT NULL,
    strike        NUMERIC(14, 4) NOT NULL,
    call_volume   BIGINT,
    put_volume    BIGINT,
    call_oi       BIGINT,
    put_oi        BIGINT,
    fetched_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, snapshot_date, expiry, strike)
);
CREATE INDEX IF NOT EXISTS idx_ocps_ticker_snap
    ON uw_scan.option_chain_per_strike(ticker, snapshot_date DESC);

-- ---------------------------------------------------------------------------
-- oi_change_events: add aggressor / premium breakdown UW returns on oi-change.
-- These columns describe the CURRENT row's volume split (UW names them prev_*
-- for legacy reasons — keep the UW naming for audit clarity).
-- ALTER TABLE ... ADD COLUMN ... NULL is a Postgres metadata-only op; safe on the
-- populated oi_change_events table.
-- ---------------------------------------------------------------------------
ALTER TABLE uw_scan.oi_change_events
    ADD COLUMN IF NOT EXISTS prev_ask_volume             BIGINT,
    ADD COLUMN IF NOT EXISTS prev_bid_volume             BIGINT,
    ADD COLUMN IF NOT EXISTS prev_mid_volume             BIGINT,
    ADD COLUMN IF NOT EXISTS prev_neutral_volume         BIGINT,
    ADD COLUMN IF NOT EXISTS prev_multi_leg_volume       BIGINT,
    ADD COLUMN IF NOT EXISTS prev_stock_multi_leg_volume BIGINT,
    ADD COLUMN IF NOT EXISTS prev_total_premium          NUMERIC(20, 4),
    ADD COLUMN IF NOT EXISTS last_ask                    NUMERIC(14, 4),
    ADD COLUMN IF NOT EXISTS last_bid                    NUMERIC(14, 4);

COMMIT;
