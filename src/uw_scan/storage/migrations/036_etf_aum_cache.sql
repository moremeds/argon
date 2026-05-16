-- 036_etf_aum_cache.sql — A1 from backend code review addendum.
-- (Originally numbered 029; renumbered to 036 after rebase against main
-- which had landed 028-034 in the cockpit-matrix branch.)
--
-- Caches the most recent AUM per ETF ticker so pipeline.py can skip the
-- per-scan /etf_info UW call when the cached value is fresh. AUM moves
-- weekly at most; a 7-day TTL gives a high cache hit rate while keeping
-- the catalog reasonably current.
--
-- Tiny table (one row per ETF on the watchlist — order of hundreds at most),
-- written rarely (per cache miss), read once per ETF scan.
--
-- Idempotent: CREATE TABLE IF NOT EXISTS.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.etf_aum_cache (
  ticker     TEXT PRIMARY KEY,
  aum        NUMERIC NOT NULL,
  fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
