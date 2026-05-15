-- 024_rescan_queue_dedupe.sql — keep one active rescan job per ticker and allow priority ordering.

SET search_path TO uw_scan, public;

ALTER TABLE uw_scan.jobs
  ADD COLUMN IF NOT EXISTS priority SMALLINT NOT NULL DEFAULT 0;

WITH ranked AS (
  SELECT
    id,
    row_number() OVER (
      PARTITION BY ticker
      ORDER BY requested_at ASC, id ASC
    ) AS rn
  FROM uw_scan.jobs
  WHERE status IN ('queued', 'running')
)
DELETE FROM uw_scan.jobs j
USING ranked r
WHERE j.id = r.id
  AND r.rn > 1;

CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_active_ticker
  ON uw_scan.jobs (ticker)
  WHERE status IN ('queued', 'running');

CREATE INDEX IF NOT EXISTS idx_jobs_queue_order
  ON uw_scan.jobs (status, priority DESC, requested_at)
  WHERE status IN ('queued', 'running');
