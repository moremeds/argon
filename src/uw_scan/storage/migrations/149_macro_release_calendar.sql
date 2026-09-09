-- 149_macro_release_calendar.sql
-- Weekly economic-release calendar, captured from UW's
-- /api/market/economic-calendar ("current & next week" window, no history)
-- and enriched at write time with a FRED actual once one is available, for
-- the small set of events with a manually verified event->series mapping
-- (`reports/macro_releases.EVENT_SERIES_MAP`).
--
-- Identity is (event, scheduled_at): UW's own pair for one calendar row. A
-- capture replay upserts forecast/prior/type in place (UW may correct a
-- forecast before the print) but never overwrites an already-recorded
-- actual/published_at/revision -- those are the fill job's exclusive lane.
--
-- actual/series_id NULL is the coverage statement: this event has no FRED
-- series we have verified matches UW's unit and transform. Never inferred,
-- never a zero.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.macro_release_calendar (
  event             TEXT NOT NULL,
  scheduled_at      TIMESTAMPTZ NOT NULL,
  type              TEXT NOT NULL,
  reported_period   TEXT NOT NULL,
  forecast          TEXT,
  prior             TEXT,
  series_id         TEXT,
  actual            NUMERIC,
  -- First actual value ever recorded for this row; a later fill differing
  -- from it is what sets revision=true. Kept even if actual is later
  -- corrected, so revision detection survives more than one correction.
  actual_first_seen NUMERIC,
  revision          BOOLEAN NOT NULL DEFAULT false,
  published_at      TIMESTAMPTZ,
  captured_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (event, scheduled_at)
);

CREATE INDEX IF NOT EXISTS idx_macro_release_calendar_scheduled
  ON uw_scan.macro_release_calendar (scheduled_at);

COMMENT ON TABLE uw_scan.macro_release_calendar
  IS 'Weekly economic-release calendar captured from UW /api/market/economic-calendar, enriched with a FRED actual/revision/published_at fill for the manually verified event->series subset (worker/jobs/macro_release_calendar.py). NULL actual/series_id means unmapped, not unavailable.';
