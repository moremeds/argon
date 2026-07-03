-- 096_watchlist_hot_flag.sql — per-ticker "hot" flag for the fast-cadence full_scan subset.
-- A UI toggle (sibling of `pinned`): hot tickers get the tight-freshness intraday
-- refresh; the budget governor caps how many hot names actually get the fast lane.
-- Idempotent.

SET search_path TO uw_scan, public;

ALTER TABLE uw_scan.watchlist
  ADD COLUMN IF NOT EXISTS hot BOOLEAN NOT NULL DEFAULT FALSE;

-- Partial index: the hot-subset job and the hot-slots meter both filter on hot=true
-- over active tickers only.
CREATE INDEX IF NOT EXISTS idx_watchlist_hot
  ON uw_scan.watchlist (ticker)
  WHERE hot IS TRUE AND removed_at IS NULL;
