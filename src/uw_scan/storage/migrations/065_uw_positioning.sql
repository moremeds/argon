-- 065_uw_positioning.sql
-- M4 (trade-framework): per-ticker UW positioning snapshot.
-- One daily row per (ticker, snapshot_date) aggregating short interest/float,
-- analyst ratings, institutional ownership, insider flow, and earnings-reaction
-- history. Column set grounded in the UW OpenAPI spec
-- (docs/uw-samples/unusual_whales_api_spec.yaml); see
-- docs/superpowers/plans/2026-05-29-trade-framework-M4-endpoint-findings.md.
SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.uw_positioning (
    ticker text NOT NULL,
    snapshot_date date NOT NULL,
    -- short interest + float (/api/shorts/{ticker}/interest-float/v2)
    si_pct_float numeric,
    si_short_interest numeric,
    si_total_float numeric,
    si_days_to_cover numeric,
    si_shares_available numeric,
    si_fee_rate numeric,
    si_rebate_rate numeric,
    si_market_date date,
    -- analyst ratings (/api/screener/analysts?ticker=)
    analyst_buy integer,
    analyst_hold integer,
    analyst_sell integer,
    analyst_target_avg numeric,
    analyst_target_hi numeric,
    analyst_target_lo numeric,
    -- institutional ownership (/api/institution/{ticker}/ownership)
    inst_holder_count integer,
    inst_total_value numeric,
    -- insider flow (/api/insider/{ticker}/ticker-flow)
    insider_buy_volume numeric,
    insider_sell_volume numeric,
    insider_net_flow numeric,
    -- earnings reactions (/api/earnings/{ticker}, history-only)
    earn_reactions_positive integer,
    earn_reactions_total integer,
    next_er_date date,
    -- provenance
    raw_jsonb jsonb,
    fetched_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, snapshot_date)
);
