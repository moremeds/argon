SET search_path TO uw_scan, public;

CREATE INDEX IF NOT EXISTS ix_oi_change_events_underlying_curr_date
    ON oi_change_events (underlying_symbol, curr_date DESC);
