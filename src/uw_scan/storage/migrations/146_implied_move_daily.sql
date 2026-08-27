-- 146_implied_move_daily.sql
-- Nightly implied-move snapshot (spec 2026-08-26-fundamentals-industry-desk
-- §5-iii): what the options market currently implies the next print will do,
-- derived from option_surface_grid_daily for names with a known upcoming
-- print (earnings_calendar, migration 144). Formula is the Brenner-
-- Subrahmanyam ATM-straddle approximation:
--
--     implied_move_pct = 0.7979 * atm_iv * sqrt(T)
--
-- where atm_iv is the mean of call_iv/put_iv at the strike nearest spot on
-- the covering expiry (first expiry >= the print's reaction day: report_date
-- for a premarket print, report_date + 1 day for afterhours AND for the
-- NULL-session ~2% UW leaves unclassified), and T is calendar days from
-- market_date to expiry, divided by 365. iv_basis records when only one side
-- of the smile was available at that strike ('call_only'/'put_only') --
-- one-sided IV is allowed and used as-is, never interpolated from the other
-- side and never dropped.
--
-- ABSENCE OF A ROW IS THE COVERAGE STATEMENT: a ticker with a calendar print
-- but no option_surface_grid_daily rows for tonight's market_date (or no
-- expiry on the grid covering the reaction day, or neither call_iv nor
-- put_iv present at the nearest strike) gets NO row here, ever -- never a
-- zero, never a stale carry-forward, never a nearest-other-date fallback.
-- The API layer renders that absence as "not covered", never blank.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.implied_move_daily (
  ticker            TEXT NOT NULL,
  market_date       DATE NOT NULL,
  report_date       DATE NOT NULL,
  expiry            DATE NOT NULL,
  strike            NUMERIC NOT NULL,
  atm_iv            NUMERIC NOT NULL,
  iv_basis          TEXT NOT NULL DEFAULT 'both'
                       CHECK (iv_basis IN ('both', 'call_only', 'put_only')),
  spot              NUMERIC NOT NULL,
  implied_move_pct  NUMERIC NOT NULL,
  implied_move_usd  NUMERIC NOT NULL,
  computed_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (ticker, market_date)
);

CREATE INDEX IF NOT EXISTS idx_implied_move_daily_ticker
  ON uw_scan.implied_move_daily (ticker, market_date DESC);

-- Serves ImpliedMoveRepository.history(ticker, report_date): every nightly
-- snapshot that targeted the SAME upcoming print, the day-by-day path the
-- desk's implied move took as it approached the report date.
CREATE INDEX IF NOT EXISTS idx_implied_move_daily_report
  ON uw_scan.implied_move_daily (ticker, report_date);

COMMENT ON TABLE uw_scan.implied_move_daily
  IS 'Nightly snapshot of the options-implied move into the next known earnings print, one row per (ticker, market_date), computed by worker/jobs/implied_move_snapshot.py from option_surface_grid_daily via the Brenner-Subrahmanyam approximation (0.7979 * atm_iv * sqrt(T)). Absence of a row for a ticker with a calendar print is the coverage statement, not a gap to fill.';
