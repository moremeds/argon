-- 068_ws_active_source.sql
-- Track which WS feed (xenon_ws | massive.com_ws) the spot consumer is
-- currently connected to, so /api/health can show primary-vs-fallback state.
SET search_path TO uw_scan, public;

ALTER TABLE ws_consumer_state
  ADD COLUMN IF NOT EXISTS active_source TEXT;
