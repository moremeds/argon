-- 003_watchlist_tables.sql — canonical watchlist + denormalized card row + OHLC + intraday quote + PCR history.
-- Idempotent. Additive to 001 / 002.

SET search_path TO uw_scan, public;

-- 1. Canonical watchlist
CREATE TABLE IF NOT EXISTS uw_scan.watchlist (
  ticker        TEXT PRIMARY KEY,
  sector        TEXT NOT NULL,
  notes         TEXT,
  pinned        BOOLEAN NOT NULL DEFAULT FALSE,
  sort_rank     INTEGER NOT NULL DEFAULT 0,
  added_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  removed_at    TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_watchlist_active
  ON uw_scan.watchlist (sector, sort_rank)
  WHERE removed_at IS NULL;

-- 2. Latest denormalized card row per ticker
CREATE TABLE IF NOT EXISTS uw_scan.watchlist_card (
  ticker            TEXT PRIMARY KEY REFERENCES uw_scan.watchlist(ticker),
  run_id            BIGINT NOT NULL REFERENCES uw_scan.scan_runs(run_id) ON DELETE RESTRICT,
  scanned_at        TIMESTAMPTZ NOT NULL,
  spot              NUMERIC(18,4),
  spot_quoted_at    TIMESTAMPTZ,
  spot_source       TEXT,

  iv_atm            NUMERIC(8,4),
  iv_rank           NUMERIC(6,2),

  setup_type        TEXT,
  setup_direction   TEXT,
  setup_score       NUMERIC(8,4),

  aggression_pct    NUMERIC(6,4),

  ret_1d            NUMERIC(8,4),
  ret_1w            NUMERIC(8,4),
  ret_30d           NUMERIC(8,4),

  gex_flip_distance NUMERIC(8,4),
  gex_flip_price    NUMERIC(18,4),
  gex_per_1pct_move NUMERIC(18,2),
  max_gex_strike    NUMERIC(18,4),
  gex_expiring_pct  NUMERIC(8,4),
  gex_expiring_date DATE,

  skew_25d_30dte    NUMERIC(8,4),

  call_oi_total     BIGINT,
  put_oi_total      BIGINT,
  pcr_oi            NUMERIC(8,4),
  pcr_vol           NUMERIC(8,4),
  pcr_delta_30d     NUMERIC(8,4),

  updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 3. Daily OHLC cache (massive.com is v1 provider)
CREATE TABLE IF NOT EXISTS uw_scan.daily_ohlc (
  ticker     TEXT NOT NULL,
  date       DATE NOT NULL,
  open       NUMERIC(18,4),
  high       NUMERIC(18,4),
  low        NUMERIC(18,4),
  close      NUMERIC(18,4) NOT NULL,
  volume     BIGINT,
  source     TEXT NOT NULL,
  fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (ticker, date)
);
CREATE INDEX IF NOT EXISTS idx_ohlc_recent
  ON uw_scan.daily_ohlc (ticker, date DESC);

-- 4. Rolling intraday quote (one row per ticker)
CREATE TABLE IF NOT EXISTS uw_scan.intraday_quote (
  ticker     TEXT PRIMARY KEY REFERENCES uw_scan.watchlist(ticker),
  price      NUMERIC(18,4) NOT NULL,
  quoted_at  TIMESTAMPTZ NOT NULL,
  fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 5. PCR daily snapshot (for 30d delta)
CREATE TABLE IF NOT EXISTS uw_scan.pcr_history (
  ticker        TEXT NOT NULL,
  snapshot_date DATE NOT NULL,
  pcr_oi        NUMERIC(8,4),
  pcr_vol       NUMERIC(8,4),
  PRIMARY KEY (ticker, snapshot_date)
);
