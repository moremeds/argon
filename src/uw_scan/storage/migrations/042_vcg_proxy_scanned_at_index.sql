-- 042_vcg_proxy_scanned_at_index.sql
--
-- VcgSnapshotRepository.fetch_latest(proxy=...) / fetch_history(proxy=...) run
--   WHERE credit_proxy = ?  ORDER BY scanned_at DESC, id DESC  LIMIT ?
-- but 041 only adds (credit_proxy, data_date DESC). Adds the matching covering
-- index; id is included so latest-wins ordering is deterministic even when two
-- snapshots land in the same scanned_at microsecond (manual + scheduled scan).
-- Idempotent.

SET search_path TO uw_scan, public;

BEGIN;

CREATE INDEX IF NOT EXISTS ix_vcg_credit_proxy_scanned_at
    ON uw_scan.vcg_snapshots (credit_proxy, scanned_at DESC, id DESC);

COMMIT;
