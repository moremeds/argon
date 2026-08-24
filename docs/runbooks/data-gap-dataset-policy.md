# Data gap dataset policy

Generated from `REGISTRY` in `src/uw_scan/reports/data_gap_healer.py` (one source of truth). Regenerate with:

```bash
uv run python -c "from uw_scan.reports.data_gap_healer import render_dataset_policy_markdown as r; open('docs/runbooks/data-gap-dataset-policy.md','w').write(r())"
```

**155 datasets** across 11 groups.

## core_watchlist

| table | audit_mode | provider | granularity | adapter | freq | reason | verified |
|---|---|---|---|---|---|---|---|
| daily_ohlc | strict_ticker_date | massive | per_ticker_range | daily_ohlc | equity_session |  |  |
| intraday_quote | freshness_only | none | none |  | liveness | live state, not a time series: a row asserts what is true NOW and is rewritten in place. A missing row means the condition does not hold, not that history was lost — there is nothing to backfill. | 2026-08-16 |
| technical_live | freshness_only | none | none |  | liveness | live state, not a time series: a row asserts what is true NOW and is rewritten in place. A missing row means the condition does not hold, not that history was lost — there is nothing to backfill. | 2026-08-16 |
| technical_vwap_anchor | excluded | none | none |  | none | user-triggered anchor state; written only on click, no expected cadence |  |

## derived_volatility

| table | audit_mode | provider | granularity | adapter | freq | reason | verified |
|---|---|---|---|---|---|---|---|
| stock_analytics_daily | strict_ticker_date | db | run_once | vol_analytics_rollup | equity_session |  |  |
| technical_daily | freshness_only | db | run_once_lookback | technical_daily | equity_session | worker/jobs/technical_daily_refresh.technical_daily_refresh recomputes the FULL series per ticker from apex bars and upserts idempotently, so ONE run heals every historical hole — the 'no per-date heal' note was right about the shape and wrong to conclude no heal exists. | 2026-08-16 |
| vrp_daily | strict_ticker_date | db | run_once | vol_analytics_rollup | equity_session |  |  |

## fundamentals

| table | audit_mode | provider | granularity | adapter | freq | reason | verified |
|---|---|---|---|---|---|---|---|
| company_sector | operational_state | uw | none |  | liveness | a per-ticker cache of the vendor's current sector, used only to route company_type. `fetched_at` records when we last ASKED, not when a fact was true, so there is no per-date series to be missing and nothing to backfill; a stale row self-heals on the next monthly fill and a name absent from it simply routes to the pooled default, exactly as before the table existed |  |
| fundamental_company_type | excluded | none | none |  | none | hand-maintainable routing table, not a time series — a missing row means the name is unrouted, which the card states explicitly |  |
| fundamental_method_params | excluded | none | none |  | none | immutable parameter rows keyed by engine_version |  |
| fundamental_method_state | excluded | none | none |  | none | singleton pointer to the active method version |  |
| fundamental_method_versions | excluded | none | none |  | none | immutable method registry, not a time series |  |
| fundamental_obs_availability | provenance | none | none |  | none | derived availability evidence for statement content versions (migration 130). Append-only, never rewritten: a rule replay collides on (obs_id, claim_key) and writes nothing. A missing claim is repaired by re-running scripts/backfill/fundamental_observation_availability.py, which spends zero provider budget and is idempotent — an operator action, not a healer adapter. Runbook: docs/runbooks/fundamental-observation-availability.md | 2026-08-24 |
| fundamental_obs_violations | provenance | none | none |  | event |  |  |
| fundamental_scores | freshness_only | db | run_once | fundamental_refresh | event | derived from fundamental_statement_obs; worker/jobs/fundamental_refresh re-runs routing -> scoring -> anchors at zero provider spend. The old reason named this job and then declined to wire it. | 2026-08-16 |
| fundamental_statement_obs | freshness_only | uw | none |  | event | quarterly filings over the fundamental universe (450 tickers as of 2026-08-18; it moves when the seeder runs), not the watchlist. Deliberately NOT wired to the healer: unlike scores/anchors this is a provider INGEST, and worker/jobs/fundamental_refresh explicitly does not ingest. Heal by running scripts/backfill/fundamental_ingest_backfill.py (insert-or-touch, safe to repeat) as a budgeted operator action, not on the nightly cron. | 2026-08-16 |
| fundamental_universe | excluded | none | none |  | none | seeded membership list, not a time series; scripts/seed_fundamental_universe.py is the source of truth |  |
| revenue_breakdown_obs | freshness_only | uw | none |  | event | revenue breakdown by XBRL axis over the fundamental universe. Deliberately NOT wired to the healer: this is a provider INGEST, and its own capture job is the only writer. Heal by re-running worker/jobs/fundamental_concentration_capture (insert-or-touch by content hash, safe to repeat) as a budgeted operator action, not on the nightly cron. Note the provider window may roll: a period that has aged out cannot be healed at all, which is why capture runs monthly rather than quarterly. | 2026-08-18 |
| valuation_anchors | freshness_only | db | run_once | fundamental_refresh | event | derived from fundamental_statement_obs + fundamental_company_type; healed by the same worker/jobs/fundamental_refresh chain as fundamental_scores (routing runs FIRST because anchors read company_type). Zero provider spend. | 2026-08-16 |

## gold_rates_macro

| table | audit_mode | provider | granularity | adapter | freq | reason | verified |
|---|---|---|---|---|---|---|---|
| cb_gold_reserves_monthly | freshness_only | none | none |  | monthly | World Gold Council source requires an interactive auth cookie and exposes no historical API; the ingest can only capture what is live at fetch time. Same failure as etf_holdings_daily. | 2026-08-16 |
| cot_gold_weekly | freshness_only | external | run_once | gold_cot | weekly |  |  |
| etf_aum_cache | freshness_only | none | none |  | equity_session | EXTERNAL-PROVIDER BLOCK, not a healer gap: the source requires an interactive auth cookie and exposes no historical API, so there is nothing for an adapter to call. Re-probe if a credential is ever provisioned. | 2026-08-16 |
| etf_flows_daily | freshness_only | none | none |  | equity_session | EXTERNAL-PROVIDER BLOCK, not a healer gap: the source requires an interactive auth cookie and exposes no historical API, so there is nothing for an adapter to call. Re-probe if a credential is ever provisioned. | 2026-08-16 |
| etf_holdings_daily | freshness_only | none | none |  | equity_session | EXTERNAL-PROVIDER BLOCK, not a healer gap: the source requires an interactive auth cookie and exposes no historical API, so there is nothing for an adapter to call. Re-probe if a credential is ever provisioned. | 2026-08-16 |
| exchange_inventory_daily | freshness_only | external | run_once | gold_comex | monthly |  |  |
| gold_posture_daily | freshness_only | db | run_once | gold_posture | equity_session |  |  |
| macro_series_daily | freshness_only | external | run_once_lookback | macro_fred | daily |  |  |
| macro_series_monthly | freshness_only | external | run_once_lookback | macro_fred | monthly |  |  |
| rates_cftc_tff_weekly | freshness_only | external | run_once_lookback | rates_fred | weekly |  |  |
| rates_fiscal_debt_daily | freshness_only | external | run_once_lookback | rates_fred | equity_session |  |  |
| rates_observations | freshness_only | external | run_once_lookback | rates_fred | equity_session |  |  |
| rates_policy_events | freshness_only | external | run_once_lookback | rates_fred | event |  |  |
| rates_policy_path | freshness_only | external | run_once_lookback | rates_fred | equity_session |  |  |
| rates_snapshots | freshness_only | external | run_once_lookback | rates_fred | equity_session |  |  |
| rates_treasury_auctions | freshness_only | external | run_once_lookback | rates_fred | weekly |  |  |
| uw_gold_options_daily | freshness_only | uw | run_once | gold_uw_options | equity_session |  |  |
| wgc_etf_monthly | freshness_only | none | none |  | monthly | World Gold Council source requires an interactive auth cookie and exposes no historical API; the ingest can only capture what is live at fetch time. Same failure as etf_holdings_daily. | 2026-08-16 |
| wgc_etf_monthly_canonical | freshness_only | none | none |  | monthly | World Gold Council source requires an interactive auth cookie and exposes no historical API; the ingest can only capture what is live at fetch time. Same failure as etf_holdings_daily. | 2026-08-16 |

## macro_evidence

| table | audit_mode | provider | granularity | adapter | freq | reason | verified |
|---|---|---|---|---|---|---|---|
| macro_context_snapshot_domains | provenance | none | none |  | none | edges of an immutable snapshot; they are written once with their parent and have no independent existence to heal |  |
| macro_context_snapshots | provenance | none | none |  | none | immutable record of a four-domain composition at an instant; reassembly belongs to the snapshot job, and inventing one would assert a coherence that was never observed |  |
| macro_domain_state_dependencies | provenance | none | none |  | none | immutable state-level lineage (migration 128); a synthesized edge would claim one domain consulted another's answer when it never did, which is a worse failure than a missing edge because it reads as provenance |  |
| macro_domain_state_evidence | provenance | none | none |  | none | immutable observation-level lineage for a state; a synthesized row would claim a state stood on evidence it never saw |  |
| macro_domain_states | provenance | none | none |  | none | immutable record of a decision at an instant; recomputation belongs to the state job, which stamps its own computed_at, and the write guard rejects any edit to a stored answer |  |
| macro_evidence_invalidations | provenance | none | none |  | none | a reviewer's judgement that accepted evidence was later found bad; there is no source to re-fetch it from, and an invented row would remove real observations from every point-in-time read after its instant |  |
| macro_observation_artifacts | provenance | none | none |  | none | immutable lineage linking an observation to the exact artifacts that witness it; synthesizing a link would fabricate evidence |  |
| macro_observations | provenance | none | none |  | none |  |  |
| macro_release_ingest_status | operational_state | none | none |  | liveness | latest ingest outcome per individual release; describes our attempts, never what the publisher said, so it is not a substitute for immutable release evidence and must not be backfilled |  |
| macro_source_artifacts | provenance | none | none |  | none |  |  |
| macro_source_status | operational_state | none | none |  | liveness | current per-source ingestion health; not immutable release history and not backfillable |  |

## operational_provenance

| table | audit_mode | provider | granularity | adapter | freq | reason | verified |
|---|---|---|---|---|---|---|---|
| api_request_audit | provenance | none | none |  | none |  |  |
| chanlun_signal_events | provenance | none | none |  | none |  |  |
| data_freshness_snapshots | provenance | none | none |  | none |  |  |
| data_gap_caveats | provenance | none | none |  | none |  |  |
| data_gap_dataset_registry | provenance | none | none |  | none |  |  |
| data_gap_items | provenance | none | none |  | none |  |  |
| data_gap_runs | provenance | none | none |  | none |  |  |
| external_api_requests | provenance | none | none |  | none |  |  |
| job_failures | excluded | none | none |  | none | live per-job failure-streak state; scheduler-maintained, nothing to backfill/heal |  |
| jobs | provenance | none | none |  | none |  |  |
| pipeline_benchmark_snapshots | provenance | none | none |  | none |  |  |
| raw_payloads | provenance | none | none |  | none |  |  |
| research_universe | excluded | none | none |  | none | cohort membership, not a time series; selected_on is a point-in-time tag, not a cadence |  |
| scan_runs | provenance | none | none |  | none |  |  |
| uw_fetch_memo | excluded | none | none |  | none | ephemeral same-day fetch dedupe cache; pruned daily, nothing to backfill/heal |  |
| volatility_backfill_status | provenance | none | none |  | none |  |  |
| watchlist_chain | excluded | none | none |  | none | chain membership, not a time series; added_at is a seed stamp, not a cadence |  |
| watchlist_ticker_events | provenance | none | none |  | none |  |  |
| worker_heartbeat | provenance | none | none |  | none |  |  |
| ws_consumer_state | operational_state | none | none |  | liveness |  |  |

## options_chain

| table | audit_mode | provider | granularity | adapter | freq | reason | verified |
|---|---|---|---|---|---|---|---|
| corporate_actions | freshness_only | massive | run_once_lookback | corporate_actions | equity_session | worker/jobs/corporate_actions_jobs.corporate_actions_refresh_once(repo, provider) re-pulls the last 12 splits / 24 dividends per ticker, so a missed run self-heals. | 2026-08-16 |
| dark_pool_events | freshness_only | none | none |  | equity_session | Written by the replay (UW honours ?date= on /darkpool/{ticker}, proven 2026-08-16) but keyed on executed_at: a name with no dark-pool print on a given session is legitimately absent, so a strict ticker-x-session audit would report phantom gaps for illiquid names. | 2026-08-16 |
| exposures_by_expiry_strike | strict_ticker_date | uw | per_ticker_date | pipeline_replay | equity_session | Replayable: UW honours ?date= on this endpoint, proven 2026-08-16 by response-hash differential (docs/research/2026-08-16-replay-endpoint-matrix.md). Healed by pipeline.run_single_stock(market_date=...). | 2026-08-16 |
| exposures_summary | strict_ticker_date | uw | per_ticker_date | pipeline_replay | equity_session | Replayable: UW honours ?date= on this endpoint, proven 2026-08-16 by response-hash differential (docs/research/2026-08-16-replay-endpoint-matrix.md). Healed by pipeline.run_single_stock(market_date=...). | 2026-08-16 |
| flow_alerts_daily_rollup | freshness_only | none | none |  | equity_session | Derived from flow_events, which UW cannot replay (byte-identical bodies across `date` values, response-hash differential 2026-08-16). A derivative of an unreplayable source is itself unreplayable — this is a MEASURED refusal, not a TODO. | 2026-08-16 |
| flow_events | freshness_only | none | none |  | equity_session | UW returns byte-identical bodies for different `date` values (response-hash differential, 2026-08-16) — historical replay would be fabrication, not backfill | 2026-08-16 |
| greek_exposure_daily | strict_ticker_date | uw | per_ticker_range | greek_exposure_daily | equity_session | UW /greek-exposure/{ticker} returns the FULL ~250-row date series in one call; measured 2026-08-16, 12 calls restored 3,000 rows across 4 outage dates |  |
| greeks_by_expiry_strike | strict_ticker_date | uw | per_ticker_date | pipeline_replay | equity_session | Replayable: UW honours ?date= on this endpoint, proven 2026-08-16 by response-hash differential (docs/research/2026-08-16-replay-endpoint-matrix.md). Healed by pipeline.run_single_stock(market_date=...). | 2026-08-16 |
| index_ohlc_daily | freshness_only | massive | run_once_lookback | index_ohlc | equity_session | worker/volatility_jobs.daily_spy_ohlc_refresh writes this (NOT the lake syncs — those write vol_index_daily). Its window was hardcoded to today-2d; it now takes lookback_days so the healer can reach an older hole. | 2026-08-16 |
| interpolated_iv_snapshots | strict_ticker_date | uw | per_ticker_date | pipeline_replay | equity_session | Replayable: UW honours ?date= on this endpoint, proven 2026-08-16 by response-hash differential (docs/research/2026-08-16-replay-endpoint-matrix.md). Healed by pipeline.run_single_stock(market_date=...). | 2026-08-16 |
| iv_rank_history | freshness_only | none | none |  | equity_session | Replayable in principle (UW honours ?date=, proven 2026-08-16) but written only for the 4 cockpit tickers by cockpit_daily_snapshot. A strict_ticker_date audit would measure it against the 170-name watchlist and invent ~166 phantom gaps per session, so it stays freshness_only. | 2026-08-16 |
| iv_smile_snapshots | freshness_only | none | none |  | equity_session | DERIVED, not UW-retention: reports/volatility_series.py builds it from greeks_by_expiry_strike via build_iv_smile_snapshot_rows inside run_volatility_backfill (NOT the nightly vol rollup — that imports only _fill_rv_from_price / persist_stock_analytics / persist_vrp_daily). Cascades off greeks_by_expiry_strike; wired in Task 7. 700,540 rows, newest 2026-08-16 — live, not legacy. | 2026-08-16 |
| iv_term_snapshots | strict_ticker_date | uw | per_ticker_date | pipeline_replay | equity_session | Replayable: UW honours ?date= on this endpoint, proven 2026-08-16 by response-hash differential (docs/research/2026-08-16-replay-endpoint-matrix.md). Healed by pipeline.run_single_stock(market_date=...). | 2026-08-16 |
| massive_fundamentals | freshness_only | massive | run_once_lookback | massive_fundamentals | equity_session | worker/jobs/fundamentals_jobs.fundamentals_refresh_once(repo, provider) re-pulls the current statement set per watchlist ticker and upserts idempotently. | 2026-08-16 |
| max_pain_by_expiry | strict_ticker_date | uw | per_ticker_date | pipeline_replay | equity_session | Replayable: UW honours ?date= on this endpoint, proven 2026-08-16 by response-hash differential (docs/research/2026-08-16-replay-endpoint-matrix.md). Healed by pipeline.run_single_stock(market_date=...). | 2026-08-16 |
| oi_by_expiry | excluded | none | none |  | equity_session | no writer anywhere in the codebase and 0 rows as of 2026-08-16; the table exists but nothing populates it | 2026-08-16 |
| oi_by_strike | strict_ticker_date | uw | per_ticker_date | pipeline_replay | equity_session | Replayable: UW honours ?date= on this endpoint, proven 2026-08-16 by response-hash differential (docs/research/2026-08-16-replay-endpoint-matrix.md). Healed by pipeline.run_single_stock(market_date=...). | 2026-08-16 |
| oi_change_events | strict_ticker_date | uw | per_ticker_date | pipeline_replay | equity_session | Replayable: UW honours ?date= on this endpoint, proven 2026-08-16 by response-hash differential (docs/research/2026-08-16-replay-endpoint-matrix.md). Healed by pipeline.run_single_stock(market_date=...). | 2026-08-16 |
| option_chain_per_strike | strict_ticker_date | uw | per_ticker_date | flow_chain_replay | equity_session | Replayable: UW honours ?date= on /option-contracts, proven 2026-08-16 by response-hash differential. Owned by flow_data_refresh (not run_single_stock), and needs that session's close to pick the +/-60% strike band — a ticker with no daily_ohlc close for the date is skipped, not stamped with a live quote. | 2026-08-16 |
| option_contract_snapshots | freshness_only | none | none |  | equity_session | Written by the replay (UW honours ?date=, proven 2026-08-16) but the table has NO date column — only run_id/ticker/option_symbol — so it cannot carry a per-ticker-date audit. Freshness is the only honest measure here. | 2026-08-16 |
| option_intraday_buckets | freshness_only | none | none |  | equity_session | UW serves this endpoint for past dates (probed 2026-08-16, HTTP 200 with rows). Blocked only by missing date plumbing in pipeline.run_single_stock — full_scan_once takes no `date`. Not a provider refusal. | 2026-08-16 |
| option_surface_grid_daily | strict_ticker_date | uw | per_ticker_date | option_surface | equity_session |  |  |
| options_volume_daily | freshness_only | none | none |  | equity_session | UW returns byte-identical bodies for different `date` values (response-hash differential, 2026-08-16) — historical replay would be fabrication, not backfill | 2026-08-16 |
| pcr_history | strict_ticker_date | uw | per_ticker_date | pipeline_replay | equity_session | Replayable: UW honours ?date= on this endpoint, proven 2026-08-16 by response-hash differential (docs/research/2026-08-16-replay-endpoint-matrix.md). Healed by pipeline.run_single_stock(market_date=...). | 2026-08-16 |
| risk_reversal_skew_history | freshness_only | none | none |  | equity_session | Self-healing: /historical-risk-reversal-skew returns a ~250-row trailing SERIES, so any nightly run re-persists the whole window. Measured 2026-08-16 at 170/170 tickers for the 2026-08-11..14 outage with no intervention. No adapter needed. | 2026-08-16 |
| short_interest_snapshots | freshness_only | none | none |  | equity_session | UW returns byte-identical bodies for different `date` values (response-hash differential, 2026-08-16) — historical replay would be fabrication, not backfill | 2026-08-16 |
| uw_dark_lit_flow_prints | strict_ticker_date | uw | per_ticker_date | uw_alpha_dark_lit | equity_session | capture_dark_lit_for(client, repo, alpha_repo, run_id, ticker, market_date) already takes the date; scripts/backfill/uw_alpha_catchup.py backfill-eventlog healed all 4 outage dates on 2026-08-16. strict_ticker_date (not freshness_only) because a per_ticker_date adapter is dispatched only from gap items. | 2026-08-16 |
| uw_gex_levels_daily | strict_ticker_date | uw | per_ticker_date | gex_levels | equity_session |  |  |
| uw_intraday_option_flow_bars | strict_ticker_date | uw | per_ticker_date | uw_alpha_intraday_flow | equity_session | capture_intraday_flow_for(...) already takes the date; same backfill-eventlog path as uw_dark_lit_flow_prints. Promoted to strict_ticker_date so the per_ticker_date adapter is actually dispatched. | 2026-08-16 |
| uw_positioning | freshness_only | none | none |  | equity_session | UW returns byte-identical bodies for different `date` values (response-hash differential, 2026-08-16) — historical replay would be fabrication, not backfill | 2026-08-16 |
| uw_short_pressure_daily | strict_ticker_date | uw | per_ticker_date | short_pressure | equity_session | interest-float is current-snapshot; ftds/volumes carry history |  |
| uw_volatility_signal_daily | strict_ticker_date | uw | per_ticker_date | volatility_signal | equity_session | VRP serves full YTD; anomaly/character ~16 recent sessions -> old dates fill VRP only |  |
| vol_index_daily | freshness_only | db | run_once_lookback | vol_index_lake | equity_session | run_vol_index_lake_sync + run_credit_etf_lake_sync (worker/jobs/) both write this table from the market-warehouse lake at zero provider cost; used to heal Aug 11-14 on 2026-08-16. | 2026-08-16 |

## regime_marketwide

| table | audit_mode | provider | granularity | adapter | freq | reason | verified |
|---|---|---|---|---|---|---|---|
| canary_snapshots | freshness_only | db | run_once_lookback | canary_recover | equity_session | scanners.canary.recover_recent_gaps(conn, schema, lookback_days=) re-derives from vol_index_daily. composite_version is part of the uniqueness key, so a snapshot from an older calibration does not count as filled. | 2026-08-16 |
| cri_snapshots | freshness_only | db | run_once_lookback | cri_recover | equity_session | scanners.cri.recover_recent_gaps(conn, schema, lookback_days=) re-derives missing snapshots from vol_index_daily at zero provider cost; used to heal Aug 11-14 on 2026-08-16. | 2026-08-16 |
| gex_snapshots | freshness_only | none | none |  | equity_session | scanners.gex.run resolves a live spot and raises without one; historical replay needs a spot source per (ticker, date). Unlike grg.run this is not fixable by truncating a fetched series. Tracked as follow-up work, not a provider refusal. | 2026-08-16 |
| grg_snapshots | strict_session | uw | per_ticker_date | grg_as_of | equity_session | grg.run(as_of=) truncates the 1Y SPY/TLT greek-exposure series AND reads spot/flip/SPY-closes at that date, so past snapshots are reconstructible rather than restamped. An as_of with fewer than 70 aligned observations honestly returns no_data. | 2026-08-16 |
| market_tide_sentiment_daily | strict_session | db | run_once_lookback | market_tide_sentiment | equity_session |  |  |
| market_tide_snapshots | strict_session | uw | per_ticker_date | market_tide | equity_session | scanners.market_tide.run already takes trading_date (and capture_spot=False for backfill); UW served all 4 outage dates with full 81-82 bar sessions. The previous 'current-session only' claim was never probed. This is the audit's calendar reference — healing it is what stops the spine going blind. | 2026-08-16 |
| matrix_state_snapshots | freshness_only | none | none |  | equity_session | Cockpit-derived: written by cockpit_daily_snapshot, which reads the option-chain tables full_scan_once cannot yet replay. Cascades off that block rather than being independently refused; wired by coverage-hardening Task 7. | 2026-08-16 |
| spx_density_forecast | freshness_only | db | run_once_lookback | spx_density_reconstruct | equity_session | worker/jobs/spx_density_forecast.reconstruct_recent_gaps(conn, schema, lookback_days=) re-derives missing cones from vol_index_daily at zero provider cost -- same shape as CRI/VCG/canary. The issue pass anchors only the freshest bar, so a session it skipped is unreachable from that pass forever (2026-08-14). Writes origin='reconstructed' and never over a prospective row; deeper seeding stays with scripts/backfill/spx_density_backfill.py. | 2026-08-18 |
| top_net_impact_snapshots | strict_session | uw | per_ticker_date | top_net_impact | equity_session | scanners.top_net_impact.run already takes trading_date; UW served 40 rows/date back to 2026-01-02 (121 sessions backfilled 2026-08-16). The 'may return only current session' claim was untested. | 2026-08-16 |
| vcg_snapshots | freshness_only | db | run_once_lookback | vcg_recover | equity_session | scanners.vcg.recover_recent_gaps(conn, schema, lookback_days=) re-derives from vol_index_daily; same shape as CRI. | 2026-08-16 |

## research_artifact

| table | audit_mode | provider | granularity | adapter | freq | reason | verified |
|---|---|---|---|---|---|---|---|
| backtest_sweep_results | research_artifact | none | none |  | event |  |  |
| backtest_sweep_runs | research_artifact | none | none |  | event |  |  |
| charm_signals | research_artifact | none | none |  | event |  |  |
| iv_source_validation | research_artifact | none | none |  | event |  |  |
| regime_backtest_daily | research_artifact | none | none |  | event |  |  |
| regime_backtest_runs | research_artifact | none | none |  | event |  |  |
| skew_analytics_snapshot | research_artifact | none | none |  | event |  |  |
| skew_directional_verdicts | research_artifact | none | none |  | event |  |  |
| skew_rv_reversion_verdicts | research_artifact | none | none |  | event |  |  |
| skew_swing_greeks | research_artifact | none | none |  | event |  |  |
| theta_harvester_candidates | research_artifact | db | none |  | event | Derived from option_surface_grid_daily; heal by re-running scripts/backfill/theta_harvester_backfill.py. Rows are absent by design for tickers with thin price history or no chain. |  |
| theta_harvester_markouts | research_artifact | db | none |  | event | Forward re-marks accrue as sessions pass; a missing horizon is not-yet-reached rather than a gap. Written by the nightly theta_harvester_markout job. |  |
| vanna_signals | research_artifact | none | none |  | event |  |  |
| vrp_30d_settlements | research_artifact | none | none |  | event |  |  |
| vrp_backtest_results | research_artifact | none | none |  | event |  |  |
| vrp_backtest_trades | research_artifact | none | none |  | event |  |  |
| vrp_directional_verdicts | research_artifact | none | none |  | event |  |  |
| vrp_dvrp_reversion | research_artifact | none | none |  | event |  |  |
| vrp_harvest_by_sector | research_artifact | none | none |  | event |  |  |
| vrp_harvest_multihorizon | research_artifact | none | none |  | event |  |  |
| vrp_harvest_verdicts | research_artifact | none | none |  | event |  |  |
| vrp_leg_nbbo | research_artifact | none | none |  | event |  |  |
| vrp_macro_entry | research_artifact | none | none |  | event |  |  |
| vrp_macro_entry_grid | research_artifact | none | none |  | event |  |  |
| vrp_macro_entry_quote | research_artifact | none | none |  | event |  |  |
| vrp_macro_signal_daily | research_artifact | none | none |  | event |  |  |
| vrp_macro_sweep_results | research_artifact | none | none |  | event |  |  |
| vrp_paper_positions | research_artifact | none | none |  | event |  |  |
| vrp_rv_validation | research_artifact | none | none |  | event |  |  |
| vrp_trade_candidates | research_artifact | none | none |  | event |  |  |

## scanner_state

| table | audit_mode | provider | granularity | adapter | freq | reason | verified |
|---|---|---|---|---|---|---|---|
| opportunity_scores | freshness_only | none | none |  | liveness | live state, not a time series: a row asserts what is true NOW and is rewritten in place. A missing row means the condition does not hold, not that history was lost — there is nothing to backfill. | 2026-08-16 |
| scanner_candidate_snapshots | freshness_only | none | none |  | equity_session | Append-only scan history (one batch per scanner run), NOT live state. Re-deriving a past scan needs the flow/GEX inputs as they stood at scan time, which the warm store overwrites — so a lost batch is genuinely unrecoverable rather than merely unwired. Freshness-monitored so a stalled scanner is still visible. | 2026-08-16 |
| signal_context_flags | freshness_only | none | none |  | liveness | live state, not a time series: a row asserts what is true NOW and is rewritten in place. A missing row means the condition does not hold, not that history was lost — there is nothing to backfill. | 2026-08-16 |
| signal_gates | freshness_only | none | none |  | liveness | live state, not a time series: a row asserts what is true NOW and is rewritten in place. A missing row means the condition does not hold, not that history was lost — there is nothing to backfill. | 2026-08-16 |
| signal_hits | freshness_only | none | none |  | liveness | live state, not a time series: a row asserts what is true NOW and is rewritten in place. A missing row means the condition does not hold, not that history was lost — there is nothing to backfill. | 2026-08-16 |
| trade_insight_ai_analyses | freshness_only | none | none |  | liveness | live state, not a time series: a row asserts what is true NOW and is rewritten in place. A missing row means the condition does not hold, not that history was lost — there is nothing to backfill. | 2026-08-16 |
| trade_insight_candidates | freshness_only | none | none |  | liveness | live state, not a time series: a row asserts what is true NOW and is rewritten in place. A missing row means the condition does not hold, not that history was lost — there is nothing to backfill. | 2026-08-16 |
| trade_insight_outcomes | freshness_only | none | none |  | liveness | live state, not a time series: a row asserts what is true NOW and is rewritten in place. A missing row means the condition does not hold, not that history was lost — there is nothing to backfill. | 2026-08-16 |
| trade_insight_snapshots | freshness_only | none | none |  | liveness | live state, not a time series: a row asserts what is true NOW and is rewritten in place. A missing row means the condition does not hold, not that history was lost — there is nothing to backfill. | 2026-08-16 |
| watchlist | freshness_only | none | none |  | liveness | live state, not a time series: a row asserts what is true NOW and is rewritten in place. A missing row means the condition does not hold, not that history was lost — there is nothing to backfill. | 2026-08-16 |
| watchlist_card | freshness_only | none | none |  | liveness | live state, not a time series: a row asserts what is true NOW and is rewritten in place. A missing row means the condition does not hold, not that history was lost — there is nothing to backfill. | 2026-08-16 |

## uw_volatility

| table | audit_mode | provider | granularity | adapter | freq | reason | verified |
|---|---|---|---|---|---|---|---|
| realized_volatility_history | strict_ticker_date | uw | per_ticker_range | realized_volatility | equity_session |  |  |
| volatility_stats_history | strict_ticker_date | uw | per_ticker_date | volatility_stats | equity_session |  |  |
