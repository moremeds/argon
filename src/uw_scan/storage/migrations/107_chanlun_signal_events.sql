-- 107_chanlun_signal_events.sql
-- Append-mostly chanlun lifecycle event log. One row per (mark_id, state)
-- transition; the nightly batch upserts ON CONFLICT DO NOTHING so re-runs over
-- the same bars are no-ops (state is a pure function of the bar series). The
-- current state of a mark is the row with the highest state precedence
-- (terminal > sublevel > pending). Future alert-pipeline input.
SET search_path TO uw_scan, public;
BEGIN;
CREATE TABLE IF NOT EXISTS uw_scan.chanlun_signal_events (
    id               BIGSERIAL PRIMARY KEY,
    ticker           TEXT NOT NULL,
    category         TEXT NOT NULL,   -- vertex | point | divergence
    kind             TEXT NOT NULL,   -- top/bottom (vertex,divergence); 1B/1S/2B/2S/3B/3S (point)
    extreme_date     DATE NOT NULL,
    extreme_price    DOUBLE PRECISION NOT NULL,
    state            TEXT NOT NULL,   -- pending | confirmed_sublevel | confirmed_native | invalidated
    reason           TEXT,            -- breach | superseded | stale | split_boundary (invalidated only)
    first_entered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    as_of            DATE NOT NULL,
    details_jsonb    JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (ticker, category, kind, extreme_date, extreme_price, state)
);
CREATE INDEX IF NOT EXISTS ix_chanlun_signal_events_ticker_latest
    ON uw_scan.chanlun_signal_events (ticker, extreme_date DESC, id DESC);
COMMIT;
