-- 145_earnings_reactions.sql
-- Per-print percentage reaction (spec 2026-08-26-fundamentals-industry-desk
-- §5-ii). Backfillable from OHLC history; rows are complete facts (both
-- closes present) — a pending print is absent, not null, and the calendar
-- row (migration 144) is what says it is expected.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.earnings_reactions (
  ticker            TEXT NOT NULL,
  report_date       DATE NOT NULL,
  session           TEXT,
  close_before_date DATE NOT NULL,
  close_before      NUMERIC NOT NULL,
  close_after_date  DATE NOT NULL,
  close_after       NUMERIC NOT NULL,
  pct_move          NUMERIC NOT NULL,
  computed_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (ticker, report_date)
);
CREATE INDEX IF NOT EXISTS idx_earnings_reactions_ticker
  ON uw_scan.earnings_reactions (ticker, report_date DESC);
