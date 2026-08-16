-- 120_freshness_sessions_missing.sql
-- Per-session coverage counter for the freshness monitor. The existing
-- coverage_pct is measured within grace_days of the table's OWN max_data_date,
-- so a single healed ticker on the newest date scores a multi-session hole as
-- 100% covered (measured 2026-08-16 on risk_reversal_skew_history: 170/170
-- reported while Aug 11-14 each held 2 of 170 tickers).
ALTER TABLE uw_scan.data_freshness_snapshots
  ADD COLUMN IF NOT EXISTS sessions_missing INTEGER;
