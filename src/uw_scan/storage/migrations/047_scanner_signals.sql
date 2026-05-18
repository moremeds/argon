-- 047_scanner_signals.sql — idempotent. Spec §6.
-- (renumbered from 045 during merge with main, which had landed 045_gold_etf_flows
-- and 046_wgc_etf_monthly; tables are unchanged.)
-- Three tables for the scanner detector framework: positive hits,
-- zero-weight context flags (colored badges), and gate audit
-- (one row per (run, ticker) explaining why the ticker passed or
-- was suppressed). All FKs cascade on scan_runs deletion.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.signal_hits (
  run_id          BIGINT NOT NULL REFERENCES uw_scan.scan_runs(run_id) ON DELETE CASCADE,
  ticker          TEXT NOT NULL,
  signal_type     TEXT NOT NULL,
  tier            SMALLINT NOT NULL CHECK (tier IN (1, 2)),
  score           NUMERIC(6,3) NOT NULL CHECK (score >= 0.0 AND score <= 1.0),
  evidence        JSONB NOT NULL,
  freshness       TEXT NOT NULL CHECK (freshness IN ('live', 'stale', 'unavailable')),
  inserted_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (run_id, ticker, signal_type)
);
CREATE INDEX IF NOT EXISTS idx_signal_hits_ticker_signal_recent
  ON uw_scan.signal_hits (ticker, signal_type, inserted_at DESC);
CREATE INDEX IF NOT EXISTS idx_signal_hits_run
  ON uw_scan.signal_hits (run_id);

CREATE TABLE IF NOT EXISTS uw_scan.signal_context_flags (
  run_id          BIGINT NOT NULL REFERENCES uw_scan.scan_runs(run_id) ON DELETE CASCADE,
  ticker          TEXT NOT NULL,
  layer           TEXT NOT NULL,
  label           TEXT NOT NULL,
  value           NUMERIC(10,4),
  inserted_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (run_id, ticker, layer)
);

CREATE TABLE IF NOT EXISTS uw_scan.signal_gates (
  run_id          BIGINT NOT NULL REFERENCES uw_scan.scan_runs(run_id) ON DELETE CASCADE,
  ticker          TEXT NOT NULL,
  earnings        TEXT NOT NULL CHECK (earnings IN ('pass', 'block')),
  liquidity       TEXT NOT NULL CHECK (liquidity IN ('pass', 'block')),
  regime          TEXT NOT NULL CHECK (regime IN ('pass', 'block')),
  inserted_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (run_id, ticker)
);
CREATE INDEX IF NOT EXISTS idx_signal_gates_ticker_recent
  ON uw_scan.signal_gates (ticker, inserted_at DESC);

COMMENT ON TABLE uw_scan.signal_hits IS
  'One row per (run, ticker, signal) emission. Composite PK; ON CONFLICT DO UPDATE on retry.';
COMMENT ON TABLE uw_scan.signal_context_flags IS
  'Zero-weight badges (e.g., PCR sentiment).';
COMMENT ON TABLE uw_scan.signal_gates IS
  'Gate audit — enables the "why is this ticker missing" UX and identifies scanner-producing runs.';
