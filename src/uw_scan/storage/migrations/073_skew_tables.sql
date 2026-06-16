-- 073_skew_tables.sql — Skew First-Principles tab.
-- skew_analytics_snapshot: one markout-ready row per (ticker, market_date, basis).
-- skew_directional_verdicts: per-bucket markout conclusions that unlock a
-- non-neutral directional lean. Both idempotent.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.skew_analytics_snapshot (
  ticker             TEXT NOT NULL,
  market_date        DATE NOT NULL,
  basis              TEXT NOT NULL DEFAULT 'eod',  -- 'eod' (canonical daily)
  spot               NUMERIC,                      -- forward-return anchor (markout-ready)
  rr_25d             NUMERIC,                      -- IV(put)-IV(call); + = put-skew
  skew_25d           NUMERIC,                      -- alias of rr_25d for UI parity
  rr_z_180d          NUMERIC,                      -- deviation vs own 180d baseline
  rr_pct_252d        NUMERIC,                      -- percentile vs own 252d baseline (0-100)
  deviation_class    TEXT,                         -- RICH | CHEAP | NORMAL
  skew_term_class    TEXT,                         -- front_steep | back_steep | flat | unknown (single expiry)
  front_rr           NUMERIC,
  back_rr            NUMERIC,
  rho_spotvol_63d    NUMERIC,
  rho_spotvol_21d    NUMERIC,
  rho_sign           INTEGER,                      -- -1 | 0 | 1
  drive_class        TEXT,                         -- PANIC | CHASE | STRUCTURAL
  asset_class        TEXT,                         -- index_macro | sector_etf | credit | single_name
  class_expected_sign TEXT,                        -- put_skew | call_skew | mixed
  borrow_flag        TEXT,                         -- hard_to_borrow | normal | unknown
  borrow_fee_rate    NUMERIC,
  days_to_cover      NUMERIC,
  earnings_gate      TEXT,                         -- block | pass | unknown
  regime             TEXT,                         -- HIGH_VOL | LOW_VOL | UNKNOWN (market)
  directional_lean   TEXT,                         -- BULLISH_TILT | BEARISH_TILT | NEUTRAL
  lean_confidence    TEXT,                         -- low | med | high
  lean_basis         TEXT,                         -- why the lean is what it is
  read_summary       TEXT,
  read_json          JSONB,
  inserted_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (ticker, market_date, basis)
);

CREATE INDEX IF NOT EXISTS ix_skew_snap_ticker_date
  ON uw_scan.skew_analytics_snapshot (ticker, market_date DESC);

COMMENT ON COLUMN uw_scan.skew_analytics_snapshot.rr_25d
  IS 'UW risk_reversal = IV(25d put) - IV(25d call); positive = put-skew. No sign transform.';
COMMENT ON COLUMN uw_scan.skew_analytics_snapshot.spot
  IS 'Close anchor for forward-return join (markout-ready). Forwards are NOT stored.';

CREATE TABLE IF NOT EXISTS uw_scan.skew_directional_verdicts (
  asset_class     TEXT NOT NULL,
  deviation_class TEXT NOT NULL,
  drive_class     TEXT NOT NULL,
  regime          TEXT NOT NULL,
  verdict         TEXT NOT NULL,    -- TRADABLE_BULL | TRADABLE_BEAR | NONE
  confidence      TEXT,             -- low | med | high
  forward_sep     NUMERIC,          -- mean T+20 forward return on borrow-clean subset
  n               INTEGER,
  borrow_clean    BOOLEAN,
  survives_gate   BOOLEAN,
  as_of           DATE,
  inserted_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (asset_class, deviation_class, drive_class, regime)
);

COMMENT ON TABLE uw_scan.skew_directional_verdicts
  IS 'Per-bucket markout conclusions. Only a TRADABLE_* row that is borrow_clean AND survives_gate unlocks a non-neutral directional lean.';

-- Supports fetch_latest_next_earnings_date (ORDER BY inserted_at DESC over a
-- ~1M-row flow_events table). Partial: only rows carrying an earnings date.
CREATE INDEX IF NOT EXISTS ix_flow_events_ticker_earnings_inserted
  ON uw_scan.flow_events (ticker, inserted_at DESC)
  WHERE next_earnings_date IS NOT NULL;
