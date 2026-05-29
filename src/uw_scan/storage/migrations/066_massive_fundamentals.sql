-- 066_massive_fundamentals.sql
-- M5 (trade-framework): per-ticker quarterly fundamentals from massive.com
-- (Polygon-shaped /vX/reference/financials) + latest dividend/split summary
-- (/v3/reference/{dividends,splits}). One row per (ticker, period_end).
-- Field names verified against the massive probe log
-- (docs/research/goyal-saretto-ipca-options/14-massive-endpoint-probe-log.md):
--   financials.income_statement.{revenues, gross_profit, operating_income_loss,
--     net_income_loss, diluted_average_shares}.value
--   financials.balance_sheet.{assets, long_term_debt, equity}.value
--   financials.cash_flow_statement.{net_cash_flow_from_operating_activities,
--     net_cash_flow_from_investing_activities}.value
-- fcf is derived (operating + investing cash flow); margins derived from the
-- raw leaves. `float` is intentionally absent here — true float comes from UW's
-- short-interest-float v2 (M4 uw_positioning.si_total_float), not massive.
SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.massive_fundamentals (
    ticker text NOT NULL,
    period_end date NOT NULL,
    fiscal_period text,
    filing_date date,
    -- income statement (raw leaves)
    revenue numeric,
    gross_profit numeric,
    operating_income numeric,
    net_income numeric,
    -- derived margins
    gross_margin numeric,
    op_margin numeric,
    net_margin numeric,
    -- balance sheet
    total_assets numeric,
    total_debt numeric,
    shareholders_equity numeric,
    diluted_shares numeric,
    -- cash flow (raw + derived fcf)
    operating_cash_flow numeric,
    investing_cash_flow numeric,
    fcf numeric,
    -- YoY diluted-share change (current / 4-quarters-ago − 1)
    share_count_delta numeric,
    -- latest corporate-action summary (carried on the most recent period row)
    last_split_date date,
    last_split_ratio numeric,
    latest_dividend_amount numeric,
    latest_dividend_ex_date date,
    -- provenance
    raw_jsonb jsonb,
    fetched_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, period_end)
);
