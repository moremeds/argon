SET search_path TO uw_scan, public;

-- Top Net Impact: market-wide ranking of tickers by net option premium
-- (net_call_premium - net_put_premium) for a session. One row per
-- (data_date, ticker); the latest capture upserts each ticker's running
-- cumulative value, so a past date holds its EOD-final snapshot.

CREATE TABLE IF NOT EXISTS top_net_impact_snapshots (
    id          BIGSERIAL PRIMARY KEY,
    data_date   DATE          NOT NULL,
    ticker      TEXT          NOT NULL,
    net_premium NUMERIC(20, 2) NOT NULL,   -- net_call_premium - net_put_premium
    rank        INT,                        -- 1-based position by net_premium DESC at last capture
    prev_rank   INT,                        -- rank at the prior capture (NULL = new this session)
    captured_at TIMESTAMPTZ   NOT NULL DEFAULT now(),
    UNIQUE (data_date, ticker)
);

CREATE INDEX IF NOT EXISTS ix_top_net_impact_date_premium
    ON top_net_impact_snapshots (data_date, net_premium DESC);
