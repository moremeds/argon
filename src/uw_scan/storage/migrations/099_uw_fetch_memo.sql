-- 099_uw_fetch_memo.sql — same-day UW fetch dedupe memo (issue #225).
-- 6+ jobs (option_surface_capture, cockpit_daily_snapshot, flow_data_refresh,
-- skew_swing_greeks, vrp_macro_entry, full_scan pipeline) independently re-fetch
-- identical slow-moving per-ticker UW data every day, burning the shared daily
-- budget (exhausted by ~08:00 ET). This table memoizes the raw JSON response
-- keyed (ticker, endpoint, as_of_date): the first caller spends budget + writes
-- the row; every same-day caller after reads it back (a budget SAVE, not a
-- spend). TTL = same trading day — a row for today is a hit; stale dates are
-- ignored by the reader and pruned by the writer. Idempotent.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.uw_fetch_memo (
    ticker      TEXT        NOT NULL,
    endpoint    TEXT        NOT NULL,
    as_of_date  DATE        NOT NULL,
    payload     JSONB       NOT NULL,
    fetched_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- budget-attribution: number of same-day callers that reused this row
    -- instead of spending UW budget again (the observable SAVE counter).
    hit_count   INTEGER     NOT NULL DEFAULT 0,
    last_hit_at TIMESTAMPTZ,
    PRIMARY KEY (ticker, endpoint, as_of_date)
);

-- Reader gates on as_of_date = today; writer prunes stale dates. Both scan by date.
CREATE INDEX IF NOT EXISTS uw_fetch_memo_as_of_idx
    ON uw_scan.uw_fetch_memo (as_of_date);
