-- 026_drop_redundant_jobs_queued_index.sql — superseded by idx_jobs_queue_order
-- (added in migration 024). Both indexes have the same partial predicate; the
-- newer one also leads with priority DESC, so it covers every query the old
-- one served (queue ordering by priority, requested_at).
--
-- Idempotent: DROP INDEX IF EXISTS is a no-op when the index has already
-- been removed. CONCURRENTLY avoids blocking concurrent jobs queue writes
-- in production. scripts/migrate.sh runs each file in autocommit (no
-- --single-transaction wrapper), so CONCURRENTLY is safe here.

SET search_path TO uw_scan, public;

DROP INDEX CONCURRENTLY IF EXISTS uw_scan.idx_jobs_queued;
