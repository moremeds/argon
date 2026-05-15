-- 023_backfill_flow_alerts_daily_rollup.sql
-- Populate flow_alerts_daily_rollup from existing per-run flow_events.
--
-- If multiple scans exist for the same ticker + market date, keep the latest
-- run_id. This matches the stock report's latest-run behavior and avoids
-- double-counting same-day rescans.

BEGIN;

WITH event_rows AS (
    SELECT
        f.run_id,
        UPPER(f.ticker) AS ticker,
        COALESCE(
            (f.created_at AT TIME ZONE 'America/New_York')::date,
            (s.started_at AT TIME ZONE 'America/New_York')::date
        ) AS trade_date,
        LOWER(COALESCE(f.option_type, '')) AS option_type,
        COALESCE(f.total_premium, 0)::numeric AS total_premium,
        COALESCE(f.total_ask_side_prem, 0)::numeric AS total_ask_side_prem,
        COALESCE(f.total_bid_side_prem, 0)::numeric AS total_bid_side_prem,
        f.alert_rule
    FROM uw_scan.flow_events f
    JOIN uw_scan.scan_runs s ON s.run_id = f.run_id
), per_run AS (
    SELECT
        run_id,
        ticker,
        trade_date,
        COUNT(*)::integer AS alert_count,
        (COUNT(*) >= 100) AS alert_count_is_limited,
        SUM(total_premium)::numeric(20, 4) AS total_premium,
        SUM(CASE WHEN option_type = 'call' THEN total_premium ELSE 0 END)::numeric(20, 4)
            AS bull_premium,
        SUM(CASE WHEN option_type = 'put' THEN total_premium ELSE 0 END)::numeric(20, 4)
            AS bear_premium,
        SUM(total_ask_side_prem)::numeric(20, 4) AS ask_side_premium,
        SUM(total_bid_side_prem)::numeric(20, 4) AS bid_side_premium
    FROM event_rows
    GROUP BY run_id, ticker, trade_date
), per_rule AS (
    SELECT
        run_id,
        ticker,
        trade_date,
        alert_rule,
        COUNT(*) AS rule_count
    FROM event_rows
    WHERE alert_rule IS NOT NULL
    GROUP BY run_id, ticker, trade_date, alert_rule
), top_rule AS (
    SELECT DISTINCT ON (run_id, ticker, trade_date)
        run_id,
        ticker,
        trade_date,
        alert_rule AS top_alert_rule
    FROM per_rule
    ORDER BY run_id, ticker, trade_date, rule_count DESC, alert_rule ASC
), ranked AS (
    SELECT
        p.*,
        t.top_alert_rule,
        ROW_NUMBER() OVER (
            PARTITION BY p.ticker, p.trade_date
            ORDER BY p.run_id DESC
        ) AS rn
    FROM per_run p
    LEFT JOIN top_rule t
      ON t.run_id = p.run_id
     AND t.ticker = p.ticker
     AND t.trade_date = p.trade_date
)
INSERT INTO uw_scan.flow_alerts_daily_rollup (
    ticker,
    trade_date,
    run_id,
    alert_count,
    alert_count_is_limited,
    total_premium,
    bull_premium,
    bear_premium,
    ask_side_premium,
    bid_side_premium,
    top_alert_rule
)
SELECT
    ticker,
    trade_date,
    run_id,
    alert_count,
    alert_count_is_limited,
    total_premium,
    bull_premium,
    bear_premium,
    ask_side_premium,
    bid_side_premium,
    top_alert_rule
FROM ranked
WHERE rn = 1
ON CONFLICT (ticker, trade_date) DO UPDATE SET
    run_id = EXCLUDED.run_id,
    alert_count = EXCLUDED.alert_count,
    alert_count_is_limited = EXCLUDED.alert_count_is_limited,
    total_premium = EXCLUDED.total_premium,
    bull_premium = EXCLUDED.bull_premium,
    bear_premium = EXCLUDED.bear_premium,
    ask_side_premium = EXCLUDED.ask_side_premium,
    bid_side_premium = EXCLUDED.bid_side_premium,
    top_alert_rule = EXCLUDED.top_alert_rule,
    updated_at = now();

COMMIT;
