-- 058_pipeline_benchmark_snapshots.sql
-- Append-only scanner/app pipeline benchmark snapshots for Grafana.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.pipeline_benchmark_snapshots (
  id BIGSERIAL PRIMARY KEY,
  captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  capture_bucket TIMESTAMPTZ NOT NULL,
  score INTEGER NOT NULL CHECK (score BETWEEN 0 AND 100),
  status TEXT NOT NULL CHECK (status IN ('OK', 'DEGRADED', 'CRITICAL')),
  freshness_score INTEGER NOT NULL CHECK (freshness_score BETWEEN 0 AND 100),
  coverage_score INTEGER NOT NULL CHECK (coverage_score BETWEEN 0 AND 100),
  throughput_score INTEGER NOT NULL CHECK (throughput_score BETWEEN 0 AND 100),
  provider_score INTEGER NOT NULL CHECK (provider_score BETWEEN 0 AND 100),
  worker_score INTEGER NOT NULL CHECK (worker_score BETWEEN 0 AND 100),
  persistence_score INTEGER NOT NULL CHECK (persistence_score BETWEEN 0 AND 100),
  watchlist_size INTEGER CHECK (watchlist_size IS NULL OR watchlist_size >= 0),
  scanner_fresh_count INTEGER CHECK (scanner_fresh_count IS NULL OR scanner_fresh_count >= 0),
  scanner_stale_count INTEGER CHECK (scanner_stale_count IS NULL OR scanner_stale_count >= 0),
  scanner_dead_count INTEGER CHECK (scanner_dead_count IS NULL OR scanner_dead_count >= 0),
  scanner_never_scanned_count INTEGER CHECK (scanner_never_scanned_count IS NULL OR scanner_never_scanned_count >= 0),
  last_full_scan_age_seconds NUMERIC CHECK (last_full_scan_age_seconds IS NULL OR last_full_scan_age_seconds >= 0),
  scan_duration_avg_seconds NUMERIC CHECK (scan_duration_avg_seconds IS NULL OR scan_duration_avg_seconds >= 0),
  scan_duration_p95_seconds NUMERIC CHECK (scan_duration_p95_seconds IS NULL OR scan_duration_p95_seconds >= 0),
  queue_depth INTEGER CHECK (queue_depth IS NULL OR queue_depth >= 0),
  oldest_queue_age_seconds NUMERIC CHECK (oldest_queue_age_seconds IS NULL OR oldest_queue_age_seconds >= 0),
  queue_drain_rate_per_minute NUMERIC CHECK (queue_drain_rate_per_minute IS NULL OR queue_drain_rate_per_minute >= 0),
  uw_latency_p95_ms INTEGER CHECK (uw_latency_p95_ms IS NULL OR uw_latency_p95_ms >= 0),
  uw_http_429 INTEGER CHECK (uw_http_429 IS NULL OR uw_http_429 >= 0),
  uw_http_4xx INTEGER CHECK (uw_http_4xx IS NULL OR uw_http_4xx >= 0),
  uw_http_5xx INTEGER CHECK (uw_http_5xx IS NULL OR uw_http_5xx >= 0),
  requests_per_minute NUMERIC CHECK (requests_per_minute IS NULL OR requests_per_minute >= 0),
  scheduler_heartbeat_lag_seconds NUMERIC CHECK (scheduler_heartbeat_lag_seconds IS NULL OR scheduler_heartbeat_lag_seconds >= 0),
  uw_worker_online_count INTEGER CHECK (uw_worker_online_count IS NULL OR uw_worker_online_count >= 0),
  uw_worker_expected_count INTEGER CHECK (uw_worker_expected_count IS NULL OR uw_worker_expected_count >= 0),
  massive_worker_online_count INTEGER CHECK (massive_worker_online_count IS NULL OR massive_worker_online_count >= 0),
  massive_worker_expected_count INTEGER CHECK (massive_worker_expected_count IS NULL OR massive_worker_expected_count >= 0),
  ws_tick_age_seconds NUMERIC CHECK (ws_tick_age_seconds IS NULL OR ws_tick_age_seconds >= 0),
  record_health_ok BOOLEAN,
  failing_record_tables TEXT[] NOT NULL DEFAULT '{}',
  details_jsonb JSONB NOT NULL DEFAULT '{}'::jsonb
);

ALTER TABLE uw_scan.pipeline_benchmark_snapshots
  ADD COLUMN IF NOT EXISTS last_full_scan_age_seconds NUMERIC
    CHECK (last_full_scan_age_seconds IS NULL OR last_full_scan_age_seconds >= 0);

ALTER TABLE uw_scan.pipeline_benchmark_snapshots
  ADD COLUMN IF NOT EXISTS queue_drain_rate_per_minute NUMERIC
    CHECK (queue_drain_rate_per_minute IS NULL OR queue_drain_rate_per_minute >= 0);

CREATE INDEX IF NOT EXISTS idx_pipeline_benchmark_snapshots_captured_at
  ON uw_scan.pipeline_benchmark_snapshots (captured_at DESC);

CREATE INDEX IF NOT EXISTS idx_pipeline_benchmark_snapshots_status_time
  ON uw_scan.pipeline_benchmark_snapshots (status, captured_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_pipeline_benchmark_snapshots_bucket
  ON uw_scan.pipeline_benchmark_snapshots (capture_bucket);
