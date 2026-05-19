-- 049_option_intraday_buckets.sql — idempotent.
-- Per-minute intraday bars for a single option contract on a given session,
-- sourced from UW /api/option-contract/{option_symbol}/intraday?date=YYYY-MM-DD.
-- ~390 buckets per contract per session. Used by the OI movers panel to
-- derive the TAPE column (peak window + share, first/last trade, sparkline).
-- One row per (option_symbol, date, start_time). Re-running the worker job
-- upserts in place; OHLC/volume/premium fields are overwritten with the
-- freshest values UW returns.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.option_intraday_buckets (
  option_symbol     TEXT        NOT NULL,
  trade_date        DATE        NOT NULL,
  start_time        TIMESTAMPTZ NOT NULL,
  open              NUMERIC(18,8),
  high              NUMERIC(18,8),
  low               NUMERIC(18,8),
  close             NUMERIC(18,8),
  avg_price         NUMERIC(18,8),
  iv_high           NUMERIC(18,8),
  iv_low            NUMERIC(18,8),
  volume_ask_side   INTEGER,
  volume_bid_side   INTEGER,
  volume_mid_side   INTEGER,
  volume_multi      INTEGER,
  premium_ask_side  NUMERIC(20,2),
  premium_bid_side  NUMERIC(20,2),
  premium_mid_side  NUMERIC(20,2),
  premium_no_side   NUMERIC(20,2),
  inserted_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (option_symbol, trade_date, start_time)
);

-- Join driver: the OI movers panel asks for "all buckets for these N contracts
-- on date D". Lookup is by (option_symbol, trade_date) — start_time is the
-- secondary sort. Without this index the per-row derivation would scan.
CREATE INDEX IF NOT EXISTS idx_option_intraday_buckets_lookup
  ON uw_scan.option_intraday_buckets (option_symbol, trade_date, start_time);

COMMENT ON TABLE uw_scan.option_intraday_buckets IS
  'UW per-minute OHLC+volume+premium for a single option contract. PK is (option_symbol, trade_date, start_time); upserts overwrite stale buckets.';
