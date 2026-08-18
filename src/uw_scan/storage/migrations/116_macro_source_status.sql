-- 116_macro_source_status.sql — mutable operational health for macro sources.
--
-- This table is deliberately separate from immutable release evidence.  It
-- describes the latest ingestion attempt, not a publisher fact.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.macro_source_status (
  source                TEXT        PRIMARY KEY CHECK (btrim(source) <> ''),
  status                TEXT        NOT NULL CHECK (status IN ('ok', 'degraded')),
  last_attempt_at       TIMESTAMPTZ NOT NULL,
  last_success_at       TIMESTAMPTZ NULL,
  consecutive_failures  INTEGER     NOT NULL DEFAULT 0
    CHECK (consecutive_failures >= 0),
  error_type            TEXT        NULL,
  error_message         TEXT        NULL,
  updated_at            TIMESTAMPTZ NOT NULL,
  CHECK (
    (status = 'ok' AND consecutive_failures = 0
      AND error_type IS NULL AND error_message IS NULL)
    OR
    (status = 'degraded' AND consecutive_failures > 0
      AND error_type IS NOT NULL)
  )
);

CREATE INDEX IF NOT EXISTS idx_macro_source_status_attempt
  ON uw_scan.macro_source_status (last_attempt_at DESC);

COMMENT ON TABLE uw_scan.macro_source_status IS
  'Mutable ingestion health; never a substitute for immutable macro evidence.';
