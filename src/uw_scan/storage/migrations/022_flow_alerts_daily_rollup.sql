-- 022_flow_alerts_daily_rollup.sql
-- Daily ticker-level summary for alert-count baselines in the Flow tab.

BEGIN;

CREATE TABLE IF NOT EXISTS uw_scan.flow_alerts_daily_rollup (
    ticker                 TEXT        NOT NULL,
    trade_date             DATE        NOT NULL,
    run_id                 BIGINT      REFERENCES uw_scan.scan_runs(run_id) ON DELETE SET NULL,
    alert_count            INTEGER     NOT NULL DEFAULT 0,
    alert_count_is_limited BOOLEAN     NOT NULL DEFAULT false,
    total_premium          NUMERIC(20, 4) NOT NULL DEFAULT 0,
    bull_premium           NUMERIC(20, 4) NOT NULL DEFAULT 0,
    bear_premium           NUMERIC(20, 4) NOT NULL DEFAULT 0,
    ask_side_premium       NUMERIC(20, 4) NOT NULL DEFAULT 0,
    bid_side_premium       NUMERIC(20, 4) NOT NULL DEFAULT 0,
    top_alert_rule         TEXT,
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_flow_alerts_daily_rollup_ticker_date
    ON uw_scan.flow_alerts_daily_rollup(ticker, trade_date DESC);

COMMENT ON COLUMN uw_scan.flow_alerts_daily_rollup.trade_date
    IS 'US/Eastern market date used for daily alert-count baselines.';
COMMENT ON COLUMN uw_scan.flow_alerts_daily_rollup.alert_count_is_limited
    IS 'True when the count hit the fetch page limit and should be interpreted as count-or-more.';

COMMIT;
