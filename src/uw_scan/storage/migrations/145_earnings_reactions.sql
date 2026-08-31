-- 145_earnings_reactions.sql
-- Per-print percentage reaction (spec 2026-08-26-fundamentals-industry-desk
-- §5-ii). Backfillable from OHLC history; rows are complete facts (both
-- closes present) — a pending print is absent, not null, and the calendar
-- row (migration 144) is what says it is expected.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.earnings_reactions (
  ticker            TEXT NOT NULL,
  report_date       DATE NOT NULL,
  -- Copied from the calendar row this reaction was computed for; the same
  -- domain as migration 144's `session`, constrained the same way so the two
  -- columns cannot drift apart. NULL is a real third value (the ~2% UW never
  -- classifies), not missing data.
  session           TEXT CHECK (session IN ('premarket', 'afterhours')),
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

COMMENT ON TABLE uw_scan.earnings_reactions IS
  'Realised percentage move around one print. A row exists only when BOTH '
  'closes were found in daily_ohlc, so a pending or unresolvable print is '
  'ABSENT rather than null — absence is the coverage statement, and the '
  'calendar row (migration 144) is what says the print was expected. Rows '
  'sourced from a filing date (calendar source=''statement_obs'') are never '
  'computed here.';
