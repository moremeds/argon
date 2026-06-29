-- Market-wide options tide (UW /api/market/market-tide), 5-min bars.
-- One row per (session date, bar timestamp). Premium/volume come from UW;
-- `spot` is captured live from intraday_quote at each worker tick (ephemeral
-- WS feed), so historical/backfilled days carry a NULL spot overlay.
SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS market_tide_snapshots (
    id               BIGSERIAL PRIMARY KEY,
    data_date        DATE        NOT NULL,
    ts               TIMESTAMPTZ NOT NULL,        -- UW bar timestamp (ET on the wire)
    net_call_premium NUMERIC(20,2) NOT NULL,
    net_put_premium  NUMERIC(20,2) NOT NULL,
    net_volume       BIGINT,
    spot             NUMERIC(14,4),               -- live index spot at capture (nullable)
    spot_ticker      TEXT,
    spot_quoted_at   TIMESTAMPTZ,
    captured_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (data_date, ts)
);

CREATE INDEX IF NOT EXISTS ix_market_tide_date_ts
    ON market_tide_snapshots (data_date, ts);
