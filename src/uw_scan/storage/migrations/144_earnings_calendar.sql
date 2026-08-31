-- 144_earnings_calendar.sql
-- Durable earnings calendar (spec 2026-08-26-fundamentals-industry-desk §5-i).
-- Accrues forward-only from the UW classified calendar; the ~2% of names UW
-- reports as report_time "unknown" appear in NEITHER slot and land here with
-- session NULL via the statement-obs discovery path — never dropped.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.earnings_calendar (
  ticker        TEXT NOT NULL,
  report_date   DATE NOT NULL,
  session       TEXT CHECK (session IN ('premarket', 'afterhours')),
  source        TEXT NOT NULL,
  first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (ticker, report_date)
);

CREATE INDEX IF NOT EXISTS idx_earnings_calendar_date
  ON uw_scan.earnings_calendar (report_date);

COMMENT ON TABLE uw_scan.earnings_calendar IS
  'Durable, forward-accruing earnings calendar. `session` NULL is a real third '
  'value — the ~2% of names UW reports as report_time "unknown", which appear '
  'in neither the premarket nor the afterhours slot and reach this table via '
  'the statement-obs discovery path with source=''statement_obs''. Those rows '
  'carry a FILING date, not a print date, so consumers that need a precise '
  'print date must exclude them.';
