-- 052_ws_consumer_state.sql
-- WS consumer heartbeat + intraday_quote source tracking + FK relaxation
SET search_path TO uw_scan, public;

-- Single-row table tracking the WS consumer's liveness + activity.
CREATE TABLE IF NOT EXISTS ws_consumer_state (
  id              SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  last_tick_at    TIMESTAMPTZ,
  last_flush_at   TIMESTAMPTZ,
  ticks_received  BIGINT NOT NULL DEFAULT 0,
  ticks_flushed   BIGINT NOT NULL DEFAULT 0,
  connection_started_at TIMESTAMPTZ,
  last_error      TEXT,
  last_error_at   TIMESTAMPTZ,
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO ws_consumer_state (id) VALUES (1) ON CONFLICT DO NOTHING;

-- Track which writer produced each intraday_quote row.
ALTER TABLE intraday_quote
  ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'massive.com_intraday';

-- A3 (adversarial fix): drop the FK from intraday_quote.ticker to watchlist(ticker).
-- The WS consumer subscribes to the watchlist, but a race (ticker removed from
-- watchlist mid-session, broker still pushes one more tick) would otherwise
-- cause an FK violation that rolls back the WHOLE flush batch — combined with
-- A2 (drain-before-write), every ticker in that batch would be lost.
-- intraday_quote already tolerates orphan tickers semantically: dashboard SQL
-- LEFT JOINs from watchlist, so orphan rows are simply ignored on read.
ALTER TABLE intraday_quote
  DROP CONSTRAINT IF EXISTS intraday_quote_ticker_fkey;
