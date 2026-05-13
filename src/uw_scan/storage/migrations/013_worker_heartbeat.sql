-- Migration 013: worker_heartbeat
--
-- One row per scheduled worker job. The job upserts its row each tick;
-- the API computes lag as now() - last_beat_at to surface worker liveness
-- (rendered in the sidebar HealthPanel).
--
-- Keyed by job_name so we can add more heartbeats later (full_scan,
-- ohlc_pull, spot_refresh) without schema changes.

CREATE TABLE IF NOT EXISTS uw_scan.worker_heartbeat (
    job_name      text         PRIMARY KEY,
    last_beat_at  timestamptz  NOT NULL DEFAULT now()
);
