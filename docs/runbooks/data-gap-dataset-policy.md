# Data gap dataset policy

Generated from `REGISTRY` in `src/uw_scan/reports/data_gap_healer.py` (one source of truth). Regenerate with:

```bash
uv run python -c "from uw_scan.reports.data_gap_healer import render_dataset_policy_markdown as r; open('docs/runbooks/data-gap-dataset-policy.md','w').write(r())"
```

**134 datasets** across 10 groups.

## core_watchlist

| table | audit_mode | provider | granularity | adapter | freq | reason |
|---|---|---|---|---|---|---|
| daily_ohlc | strict_ticker_date | massive | per_ticker_range | daily_ohlc | equity_session |  |
| intraday_quote | freshness_only | none | none |  | liveness |  |
| technical_live | freshness_only | none | none |  | liveness |  |
| technical_vwap_anchor | excluded | none | none |  | none | user-triggered anchor state; written only on click, no expected cadence |

## derived_volatility

| table | audit_mode | provider | granularity | adapter | freq | reason |
|---|---|---|---|---|---|---|
| stock_analytics_daily | strict_ticker_date | db | run_once | vol_analytics_rollup | equity_session |  |
| technical_daily | freshness_only | none | none |  | equity_session | full series recomputed nightly from apex bars; no per-date heal |
| vrp_daily | strict_ticker_date | db | run_once | vol_analytics_rollup | equity_session |  |

## gold_rates_macro

| table | audit_mode | provider | granularity | adapter | freq | reason |
|---|---|---|---|---|---|---|
| cb_gold_reserves_monthly | freshness_only | none | none |  | monthly | source needs auth cookie / no historical API (audit-only) |
| cot_gold_weekly | freshness_only | external | run_once | gold_cot | weekly |  |
| etf_aum_cache | freshness_only | none | none |  | equity_session | source needs auth cookie / no historical API (audit-only) |
| etf_flows_daily | freshness_only | none | none |  | equity_session | source needs auth cookie / no historical API (audit-only) |
| etf_holdings_daily | freshness_only | none | none |  | equity_session | source needs auth cookie / no historical API (audit-only) |
| exchange_inventory_daily | freshness_only | external | run_once | gold_comex | monthly |  |
| gold_posture_daily | freshness_only | db | run_once | gold_posture | equity_session |  |
| macro_series_daily | freshness_only | external | run_once_lookback | macro_fred | daily |  |
| macro_series_monthly | freshness_only | external | run_once_lookback | macro_fred | monthly |  |
| rates_cftc_tff_weekly | freshness_only | external | run_once_lookback | rates_fred | weekly |  |
| rates_fiscal_debt_daily | freshness_only | external | run_once_lookback | rates_fred | equity_session |  |
| rates_observations | freshness_only | external | run_once_lookback | rates_fred | equity_session |  |
| rates_policy_events | freshness_only | external | run_once_lookback | rates_fred | event |  |
| rates_policy_path | freshness_only | external | run_once_lookback | rates_fred | equity_session |  |
| rates_snapshots | freshness_only | external | run_once_lookback | rates_fred | equity_session |  |
| rates_treasury_auctions | freshness_only | external | run_once_lookback | rates_fred | weekly |  |
| uw_gold_options_daily | freshness_only | uw | run_once | gold_uw_options | equity_session |  |
| wgc_etf_monthly | freshness_only | none | none |  | monthly | source needs auth cookie / no historical API (audit-only) |
| wgc_etf_monthly_canonical | freshness_only | none | none |  | monthly | source needs auth cookie / no historical API (audit-only) |

## macro_evidence

| table | audit_mode | provider | granularity | adapter | freq | reason |
|---|---|---|---|---|---|---|
| macro_observations | provenance | none | none |  | none |  |
| macro_source_artifacts | provenance | none | none |  | none |  |

## operational_provenance

| table | audit_mode | provider | granularity | adapter | freq | reason |
|---|---|---|---|---|---|---|
| api_request_audit | provenance | none | none |  | none |  |
| chanlun_signal_events | provenance | none | none |  | none |  |
| data_freshness_snapshots | provenance | none | none |  | none |  |
| data_gap_caveats | provenance | none | none |  | none |  |
| data_gap_dataset_registry | provenance | none | none |  | none |  |
| data_gap_items | provenance | none | none |  | none |  |
| data_gap_runs | provenance | none | none |  | none |  |
| external_api_requests | provenance | none | none |  | none |  |
| job_failures | excluded | none | none |  | none | live per-job failure-streak state; scheduler-maintained, nothing to backfill/heal |
| jobs | provenance | none | none |  | none |  |
| pipeline_benchmark_snapshots | provenance | none | none |  | none |  |
| raw_payloads | provenance | none | none |  | none |  |
| research_universe | excluded | none | none |  | none | cohort membership, not a time series; selected_on is a point-in-time tag, not a cadence |
| scan_runs | provenance | none | none |  | none |  |
| uw_fetch_memo | excluded | none | none |  | none | ephemeral same-day fetch dedupe cache; pruned daily, nothing to backfill/heal |
| volatility_backfill_status | provenance | none | none |  | none |  |
| watchlist_chain | excluded | none | none |  | none | chain membership, not a time series; added_at is a seed stamp, not a cadence |
| watchlist_ticker_events | provenance | none | none |  | none |  |
| worker_heartbeat | provenance | none | none |  | none |  |
| ws_consumer_state | operational_state | none | none |  | liveness |  |

## options_chain

| table | audit_mode | provider | granularity | adapter | freq | reason |
|---|---|---|---|---|---|---|
| corporate_actions | freshness_only | none | none |  | equity_session | UW-retention/event-log shaped; freshness-monitored, no auto-backfill |
| dark_pool_events | freshness_only | none | none |  | equity_session | UW-retention/event-log shaped; freshness-monitored, no auto-backfill |
| exposures_by_expiry_strike | freshness_only | none | none |  | equity_session | UW-retention/event-log shaped; freshness-monitored, no auto-backfill |
| exposures_summary | freshness_only | none | none |  | equity_session | UW-retention/event-log shaped; freshness-monitored, no auto-backfill |
| flow_alerts_daily_rollup | freshness_only | none | none |  | equity_session | derived from flow_events; heal adapter is a TODO (audit-only) |
| flow_events | freshness_only | none | none |  | equity_session | UW-retention/event-log shaped; freshness-monitored, no auto-backfill |
| greek_exposure_daily | strict_ticker_date | uw | per_ticker_date | greek_exposure_daily | equity_session | UW aggregate returns the current snapshot only; past dates -> no_data |
| greeks_by_expiry_strike | freshness_only | none | none |  | equity_session | UW-retention/event-log shaped; freshness-monitored, no auto-backfill |
| index_ohlc_daily | freshness_only | none | none |  | equity_session | UW-retention/event-log shaped; freshness-monitored, no auto-backfill |
| interpolated_iv_snapshots | freshness_only | none | none |  | equity_session | UW-retention/event-log shaped; freshness-monitored, no auto-backfill |
| iv_rank_history | freshness_only | none | none |  | equity_session | UW-retention/event-log shaped; freshness-monitored, no auto-backfill |
| iv_smile_snapshots | freshness_only | none | none |  | equity_session | UW-retention/event-log shaped; freshness-monitored, no auto-backfill |
| iv_term_snapshots | freshness_only | none | none |  | equity_session | UW-retention/event-log shaped; freshness-monitored, no auto-backfill |
| massive_fundamentals | freshness_only | none | none |  | equity_session | UW-retention/event-log shaped; freshness-monitored, no auto-backfill |
| max_pain_by_expiry | freshness_only | none | none |  | equity_session | UW-retention/event-log shaped; freshness-monitored, no auto-backfill |
| oi_by_expiry | freshness_only | none | none |  | equity_session | UW-retention/event-log shaped; freshness-monitored, no auto-backfill |
| oi_by_strike | freshness_only | none | none |  | equity_session | UW-retention/event-log shaped; freshness-monitored, no auto-backfill |
| oi_change_events | freshness_only | none | none |  | equity_session | UW-retention/event-log shaped; freshness-monitored, no auto-backfill |
| option_chain_per_strike | freshness_only | none | none |  | equity_session | UW-retention/event-log shaped; freshness-monitored, no auto-backfill |
| option_contract_snapshots | freshness_only | none | none |  | equity_session | UW-retention/event-log shaped; freshness-monitored, no auto-backfill |
| option_intraday_buckets | freshness_only | none | none |  | equity_session | UW-retention/event-log shaped; freshness-monitored, no auto-backfill |
| option_surface_grid_daily | strict_ticker_date | uw | per_ticker_date | option_surface | equity_session |  |
| options_volume_daily | freshness_only | none | none |  | equity_session | UW-retention/event-log shaped; freshness-monitored, no auto-backfill |
| pcr_history | freshness_only | none | none |  | equity_session | UW-retention/event-log shaped; freshness-monitored, no auto-backfill |
| risk_reversal_skew_history | freshness_only | none | none |  | equity_session | UW-retention/event-log shaped; freshness-monitored, no auto-backfill |
| short_interest_snapshots | freshness_only | none | none |  | equity_session | UW-retention/event-log shaped; freshness-monitored, no auto-backfill |
| uw_dark_lit_flow_prints | freshness_only | none | none |  | equity_session | UW-retention/event-log shaped; freshness-monitored, no auto-backfill |
| uw_gex_levels_daily | strict_ticker_date | uw | per_ticker_date | gex_levels | equity_session |  |
| uw_intraday_option_flow_bars | freshness_only | none | none |  | equity_session | UW-retention/event-log shaped; freshness-monitored, no auto-backfill |
| uw_positioning | freshness_only | none | none |  | equity_session | UW-retention/event-log shaped; freshness-monitored, no auto-backfill |
| uw_short_pressure_daily | strict_ticker_date | uw | per_ticker_date | short_pressure | equity_session | interest-float is current-snapshot; ftds/volumes carry history |
| uw_volatility_signal_daily | strict_ticker_date | uw | per_ticker_date | volatility_signal | equity_session | VRP serves full YTD; anomaly/character ~16 recent sessions -> old dates fill VRP only |
| vol_index_daily | freshness_only | none | none |  | equity_session | UW-retention/event-log shaped; freshness-monitored, no auto-backfill |

## regime_marketwide

| table | audit_mode | provider | granularity | adapter | freq | reason |
|---|---|---|---|---|---|---|
| canary_snapshots | freshness_only | none | none |  | equity_session | regime scanner output; re-derive needs historical inputs (audit-only) |
| cri_snapshots | freshness_only | none | none |  | equity_session | regime scanner output; re-derive needs historical inputs (audit-only) |
| gex_snapshots | freshness_only | none | none |  | equity_session | regime scanner output; re-derive needs historical inputs (audit-only) |
| grg_snapshots | freshness_only | none | none |  | equity_session | regime scanner output; re-derive needs historical inputs (audit-only) |
| market_tide_sentiment_daily | strict_session | db | run_once_lookback | market_tide_sentiment | equity_session |  |
| market_tide_snapshots | strict_session | none | none |  | equity_session | UW market-tide is current-session; historical heal TODO (audit-only) |
| matrix_state_snapshots | freshness_only | none | none |  | equity_session | regime scanner output; re-derive needs historical inputs (audit-only) |
| spx_density_forecast | research_artifact | db | none |  | equity_session | Display-only v13 density cone shadow log. Prospective rows are forward-in-time only; historical fill is origin='reconstructed' via scripts/backfill/spx_density_backfill.py. |
| top_net_impact_snapshots | strict_session | none | none |  | equity_session | UW historical endpoint may return only current session; heal TODO |
| vcg_snapshots | freshness_only | none | none |  | equity_session | regime scanner output; re-derive needs historical inputs (audit-only) |

## research_artifact

| table | audit_mode | provider | granularity | adapter | freq | reason |
|---|---|---|---|---|---|---|
| backtest_sweep_results | research_artifact | none | none |  | event |  |
| backtest_sweep_runs | research_artifact | none | none |  | event |  |
| charm_signals | research_artifact | none | none |  | event |  |
| iv_source_validation | research_artifact | none | none |  | event |  |
| regime_backtest_daily | research_artifact | none | none |  | event |  |
| regime_backtest_runs | research_artifact | none | none |  | event |  |
| skew_analytics_snapshot | research_artifact | none | none |  | event |  |
| skew_directional_verdicts | research_artifact | none | none |  | event |  |
| skew_rv_reversion_verdicts | research_artifact | none | none |  | event |  |
| skew_swing_greeks | research_artifact | none | none |  | event |  |
| theta_harvester_candidates | research_artifact | db | none |  | event | Derived from option_surface_grid_daily; heal by re-running scripts/backfill/theta_harvester_backfill.py. Rows are absent by design for tickers with thin price history or no chain. |
| theta_harvester_markouts | research_artifact | db | none |  | event | Forward re-marks accrue as sessions pass; a missing horizon is not-yet-reached rather than a gap. Written by the nightly theta_harvester_markout job. |
| vanna_signals | research_artifact | none | none |  | event |  |
| vrp_30d_settlements | research_artifact | none | none |  | event |  |
| vrp_backtest_results | research_artifact | none | none |  | event |  |
| vrp_backtest_trades | research_artifact | none | none |  | event |  |
| vrp_directional_verdicts | research_artifact | none | none |  | event |  |
| vrp_dvrp_reversion | research_artifact | none | none |  | event |  |
| vrp_harvest_by_sector | research_artifact | none | none |  | event |  |
| vrp_harvest_multihorizon | research_artifact | none | none |  | event |  |
| vrp_harvest_verdicts | research_artifact | none | none |  | event |  |
| vrp_leg_nbbo | research_artifact | none | none |  | event |  |
| vrp_macro_entry | research_artifact | none | none |  | event |  |
| vrp_macro_entry_grid | research_artifact | none | none |  | event |  |
| vrp_macro_entry_quote | research_artifact | none | none |  | event |  |
| vrp_macro_signal_daily | research_artifact | none | none |  | event |  |
| vrp_macro_sweep_results | research_artifact | none | none |  | event |  |
| vrp_paper_positions | research_artifact | none | none |  | event |  |
| vrp_rv_validation | research_artifact | none | none |  | event |  |
| vrp_trade_candidates | research_artifact | none | none |  | event |  |

## scanner_state

| table | audit_mode | provider | granularity | adapter | freq | reason |
|---|---|---|---|---|---|---|
| opportunity_scores | freshness_only | none | none |  | liveness |  |
| scanner_candidate_snapshots | freshness_only | none | none |  | liveness |  |
| signal_context_flags | freshness_only | none | none |  | liveness |  |
| signal_gates | freshness_only | none | none |  | liveness |  |
| signal_hits | freshness_only | none | none |  | liveness |  |
| trade_insight_ai_analyses | freshness_only | none | none |  | liveness |  |
| trade_insight_candidates | freshness_only | none | none |  | liveness |  |
| trade_insight_outcomes | freshness_only | none | none |  | liveness |  |
| trade_insight_snapshots | freshness_only | none | none |  | liveness |  |
| watchlist | freshness_only | none | none |  | liveness |  |
| watchlist_card | freshness_only | none | none |  | liveness |  |

## uw_volatility

| table | audit_mode | provider | granularity | adapter | freq | reason |
|---|---|---|---|---|---|---|
| realized_volatility_history | strict_ticker_date | uw | per_ticker_range | realized_volatility | equity_session |  |
| volatility_stats_history | strict_ticker_date | uw | per_ticker_date | volatility_stats | equity_session |  |
