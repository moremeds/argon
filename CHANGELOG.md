# Changelog

All notable changes to Argon are documented here. Format loosely based on
[Keep a Changelog](https://keepachangelog.com/) with semver versioning.
`VERSION` is the source of truth; `pyproject.toml` and `web/package.json`
version in lockstep (enforced by `scripts/release/version_sync_check.py`).

## [Unreleased]

### Added

- **SVI surface-fit feasibility + residual edge test (research spike).**
  `scripts/research/svi_fit.py` — pure raw-SVI (Gatheral) smile fit + butterfly/calendar
  no-arb diagnostics + delta-forward anchor, unit-tested (`tests/unit/test_svi_fit.py`) —
  plus two read-only probes over `option_surface_grid_daily`. Verdict in
  `docs/research/svi-surface-fit/`: raw-SVI fits liquid smiles to <0.5 vol-pt residual,
  arb-free, but the fitted-vs-marked residual — while a genuine mean-reverting signal
  (autocorr 0.56) — carries **no taker edge** (~\$0.18/contract, below one option
  commission). Do not build the signal layer. Adds `scipy` (main dep, needed by the tested
  fit); figs use matplotlib from the existing `research` dep-group. Also surfaced: the
  mini's IB canary (`iv_source_validation`) had captured no IB IV (0/1026 rows) through
  07-02 — a stale pre-key env frozen at worker fork, not a missing key (the mini's argon
  `.env` has `XENON_QUERY_API_KEY`); the Jul 4 worker restart already picked up the key,
  so the canary should self-heal on its next weekday run.

## [0.7.1] — 2026-07-04


### Fixed

- **HealthPanel "API OFFLINE" flicker.** The sidebar rapidly toggled `API
  OFFLINE` / everything `UNKNOWN` even while the API was up. Root cause: the
  `/api/health` record-coverage ("Query Coverage") scan costs ~15–20s cold but
  its cache TTL was only 15s, so a fresh 20s query fired on nearly every 5s
  poll, stacking on one DB and blowing the browser fetch timeout. Two changes:
  (1) `_RECORD_HEALTH_CACHE_TTL_SECONDS` 15→120 so the expensive scan runs at
  most once every 2 min; (2) the poll now caps each request at an 8s timeout and
  keeps the last-good snapshot on a transient miss, only showing `OFFLINE` after
  3 consecutive failures (a real outage) instead of flickering on one slow poll.
  Polls are serialized (next scheduled only after the current settles) so an 8s
  timeout under a 5s interval can't overlap and let a stale timed-out poll
  corrupt the consecutive-failure count.
- **HealthPanel "Query Coverage" permanently ALERT.** The record-coverage check
  auto-discovered every ticker+timestamp table and expected ~90% watchlist
  coverage in an 8h window, with no market-calendar awareness — so it flashed
  ALERT every weekend/holiday/overnight (no scans run → 0 rows) and, during RTH,
  for sparse/research tables that structurally never reach 90% coverage. Now:
  (1) the check is market-calendar aware — when no full-scan cron was due in the
  window it reads healthy and skips the per-table scan (mirrors the WS-consumer
  relaxation); (2) the structurally-sparse candidate / research / unusual-activity
  tables (`signal_hits`, `scanner_candidate_snapshots`, `vrp_trade_candidates`,
  `vrp_paper_positions`, `vrp_backtest_trades`, `vrp_macro_sweep_results`,
  `corporate_actions`, `iv_source_validation`, `short_interest_snapshots`,
  `flow_events`, `dark_pool_events`, `oi_change_events`) are excluded — the
  event tables insert nothing for a ticker with no events, so they never reach
  90% coverage (but `signal_gates` is kept — it is written once per scanned
  ticker, so its coverage is a real scanner-persistence signal); (3) the nightly
  `option_surface_grid_daily` / `flow_alerts_daily_rollup` tables use the 24h
  window instead of 8h.
## [0.7.0] — 2026-07-04


### Added

- **UW daily-budget governor + RTH cadence scale-up** (targets ~70k live / ~25k
  research under the shared 120k account cap). New `sources/uw_budget.py` reads
  today's UW spend from `external_api_requests`, splits jobs into a `live` pool
  (`full_scan`, `full_scan_hot`, `rescan_tick`) and a `research` pool (everything
  else incl. `*_backfill`), and enforces per-pool ceilings plus an account-wide
  total guard (from the `official_daily_count` header, which also sees
  un-instrumented consumers). Under budget pressure `full_scan` scans hot-first
  and drops the cold tail (`max_tickers` cap) instead of 429-storming; research
  jobs yield first. Env: `UW_BUDGET_GOVERNOR_ENABLED`, `UW_LIVE_DAILY_CEILING`
  (80000), `UW_RESEARCH_DAILY_CEILING` (30000), `UW_TOTAL_DAILY_GUARD` (105000),
  `UW_DAILY_LIMIT` (120000).
- **Hot-subset fast lane** — a per-ticker `hot` flag (migration 096, UI toggle
  mirroring the pin: `HotButton` + watchlist hot-slots meter). Hot tickers get a
  tight-freshness intraday `full_scan` (`full_scan_hot` job, `*/5 9-16` ET,
  primary-uw-only, governor-capped). Env: `FULL_SCAN_HOT_ENABLED`,
  `FULL_SCAN_HOT_CRON`, `FULL_SCAN_HOT_STALE_MINUTES`, `FULL_SCAN_HOT_MAX_TICKERS`.
- **Intraday GEX research series** — `regime_gex_scan` expanded from the
  SPX/SPY/TLT core to the index family + M7 and moved to a split RTH-fast
  (`*/2`) / off-hours-slow (`*/15`) weekday cadence, building the append-only
  intraday GEX/DEX series UW only serves at EOD. Env:
  `GEX_SCAN_RTH_INTERVAL_MINUTES`, `GEX_SCAN_OFFHOURS_INTERVAL_MINUTES`,
  `GEX_SCAN_TICKERS`.


- Unified backtest harness `src/uw_scan/backtest/` (no-lookahead replay engine,
  time-ordered holdout splitter, walkforward+quarter OOS gates, legacy-convention
  metrics, persist-as-you-go sweep runner) + migration 095
  (`backtest_sweep_runs`/`backtest_sweep_results`). `skew_markout`, `vrp_markout`,
  `vrp_markout_core`, and `vrp_backtest` gate/holdout logic is now fully
  deduplicated onto it (behavior-identical) — no private copies remain;
  `scripts/_vrp_macro_param_sweep.py` synthesis grid now persists its full trace.

### Changed

- `full_scan_stale_after_hours` is now a float defaulting to **0.33** (~20-min
  watchlist freshness, was int `1`). `UW_SCAN_FULL_SCAN_STALE_HOURS` accepts
  fractional hours. The health "expected full scans missed" liveness alarm is
  now decoupled from card freshness onto its own grace knob
  (`health_full_scan_missed_grace_hours`, default 1.0h) so a transient
  governor-driven skip no longer false-alarms; sustained live-budget starvation
  (>1h) still alarms, as it should. The benchmark coverage gate
  (`benchmark/collector.py`, same `>=2` missed-scan threshold) shares the knob so
  the two "missed scans" signals stay consistent.
- Backfill scripts (`market_tide`, `greek_exposure_daily_refresh`,
  `intraday_buckets`, `option_surface`) now route UW calls through
  `ExternalApiRequestRecorder`, so their spend is attributed to the research
  pool and visible to the governor (Phase 0).
- **CLAUDE.md refresh + AGENTS.md deduplication.** All 14 in-repo CLAUDE.md
  files audited against the current tree and de-staled (api routers 6→17,
  cards/reports rewritten as domain-group maps, worker's dead
  `jobs/spot_refresh.py` entry removed, web stock `[tab]/` router + `/rates`
  `/vrp` routes documented, tests layout corrected). Four standing rules
  promoted from session memory (CHANGELOG-rides-the-feature-PR, smoke tests via
  the real worker path, R2-primary for EOD/backfill, workers-don't-hot-reload).
  `AGENTS.md` is now a symlink to `CLAUDE.md` (its two unique lines — worktree
  location rule, `unusual_whales_api_spec.yaml` pointer — were merged in first).
## [0.6.0] — 2026-07-02


### Added

- **Gold/rates tables added to the daily freshness monitor.** `etf_flows_daily`,
  `wgc_etf_monthly`, `cb_gold_reserves_monthly`, and `exchange_inventory_daily`
  join `MONITORED_TABLES` (`/api/health` `freshness` block, nightly
  `data_freshness_monitor`) — none were previously monitored, which is why
  `etf_flows_daily`'s ~7-week silent staleness (fixed in v0.5.1) required a
  manual investigation to catch instead of surfacing automatically.
  `_DATE_COL_PREFERENCE` now recognizes `obs_date`/`obs_month` (the gold/rates
  convention, distinct from the options-chain `market_date`/`trade_date`).
  `MonitoredTable` gains a per-table `grace_days` override so monthly-cadence
  sources (WGC releases monthly; COMEX/LBMA vault data is effectively monthly)
  don't cry wolf under the 4-day default meant for daily options data.
  `wgc_etf_monthly` / `cb_gold_reserves_monthly` / `exchange_inventory_daily`
  will show `frozen=true` until someone provisions a `WGC_GOLDHUB_COOKIE` or a
  licensed COMEX data source — that's accurate, not noise.
- **Freshness monitor coverage expanded from 12 to 48 tables.** A follow-up
  audit of the full 118-table data-gap registry found ~40 more genuinely
  continuous tables with zero prior `/api/health` visibility: the durable
  option-surface IV grid, the options-chain pipeline (greeks/IV term/skew/max
  pain/exposures), regime scanner outputs (GEX/CRI/VCG/GRG/canary), and the
  remaining FRED/rates/gold sources not already known to be blocked.
  `_DATE_COL_PREFERENCE` now also recognizes `data_date` and `snapshot_date`.
  `MonitoredTable` gains a `date_col_override` for the handful of tables with
  a one-off column name (`auction_date`, `record_date`, `event_date`) rather
  than growing the shared preference list with names that could collide on a
  future table. Deliberately **not** added: `dark_pool_events`, `flow_events`,
  `option_contract_snapshots`, `massive_fundamentals`, `short_interest_snapshots`
  (no DATE-typed column, only TIMESTAMPTZ event/insert timestamps —
  `compute_freshness` only handles DATE columns today) and `corporate_actions`
  (has both a date and ticker column, but is genuinely event-sparse per ticker;
  watchlist-scope coverage would produce a permanent false LOW COVERAGE
  warning, not a real signal).
- **Freshness grace periods derived from each table's real cadence, not hand
  guesses.** `MonitoredTable.grace_days` now defaults to a lookup on the
  gap-healer registry's `expected_frequency` (`_FREQUENCY_GRACE_DAYS`:
  equity_session/daily → 4, weekly → 10, monthly/event → 45) instead of each
  table separately guessing its own number — the exact class of manual
  judgment that caused 4 real scoping bugs earlier in this same pass (see
  "correct scope for 4 index/regime-only tables" below). Also fixes the
  registry itself: `wgc_etf_monthly`, `cb_gold_reserves_monthly`,
  `exchange_inventory_daily`, `rates_cftc_tff_weekly`, and
  `rates_treasury_auctions` were defaulted to `expected_frequency=
  "equity_session"` despite being monthly/weekly; `rates_policy_events`
  becomes `"event"` (FOMC-driven, no fixed periodic SLA).
- **Freshness-autoheal: a same-night retry with a circuit breaker.** A frozen
  table with a gap-healer adapter gets one scoped retrigger the same night
  (`DATA_FRESHNESS_AUTOHEAL_ENABLED`, off by default) — a second chance for a
  table the 20:00 ET gap-healer left frozen from budget exhaustion or a
  transient failure, not a substitute for that nightly job. A circuit breaker
  (`DATA_FRESHNESS_AUTOHEAL_CIRCUIT_BREAKER_NIGHTS`, default 3 consecutive
  frozen nights) stops retriggering a genuinely unfixable source (missing
  credential, licensed data feed) instead of burning budget on it forever;
  tripped tables surface on `/api/health` (`freshness.autoheal_circuit_broken`)
  so a human knows to step in. Verified against a dry-run on real prod data:
  of today's 3 frozen tables, 2 have no adapter at all and the third would
  already have its circuit breaker tripped — autoheal correctly does nothing
  for any of today's known-broken sources.

### Removed

- **Dropped 4 permanently-empty legacy tables and their dead code paths**
  (migration `094`): `option_surface_snapshots` (S1 placeholder superseded by
  `option_surface_grid_daily`), `scan_universe` + `scan_results` (S2 full-scan
  persistence for a since-deleted Streamlit prototype — only reachable from
  an integration test, never from a scheduler job or the live Scanner page),
  and `structure_ideas` (a trade-structure stub whose writer had zero
  callers). Removed the now-dead `pipeline.run_full_scan`, `reports/scan.py`,
  `scan_universe.py`, five `_ScanResultsMixin` methods, `insert_structure_idea`,
  a dead marketcap-fallback join in `storage/watchlist.py`, and the
  corresponding registry/test entries. The live Scanner page is unaffected —
  it reads `scanner_candidate_snapshots` / `signal_hits` / `signal_gates` /
  `signal_context_flags`, none of which touch these tables.
## [0.5.1] — 2026-07-02

### Fixed

- **`gold_etf_holdings_ingest_job` used the host's local clock instead of ET.**
  `date.today()` picked up the mini's system-local date (ahead of US Eastern by
  ~12h) to compute the UW `/etfs/{ticker}/in-outflow` date range, so on a host
  whose local day has already rolled past midnight ET, `end_date` became a
  "future EST date" and UW rejected every call with HTTP 422 — silently, since
  the fetch is wrapped in a per-ticker `try/except: logger.warning`. `GLD` /
  `IAU` / `GLDM` in/outflow data (`etf_flows_daily`) stopped refreshing as a
  result. Now computes "today" via `datetime.now(ZoneInfo(rth_tz))`, matching
  the ET-aware pattern already used by `flow_data_refresh`, `regime_live`,
  `vrp_macro_signal`, and others.
- **xdist sharding blind spot** — `_reset_to_baseline` in `tests/integration/conftest.py`
  now drops any tables the test under execution created that are not in the
  post-migration baseline snapshot, before the `TRUNCATE … CASCADE` restore.
  Previously, an ad-hoc `CREATE TABLE` inside a test survived across tests within
  the same xdist worker and was only exposed by the unsharded release-verify gate
  (which runs the full suite serially in a single DB). The fix kills the whole
  class: drop extras → truncate baseline → copy baseline back.
- **`macmini-prod.sh` npm ci flakiness** — `rm -rf web/node_modules` is now run
  before `npm ci` so a partially-written `node_modules` (e.g. the `ENOTEMPTY:
  rmdir lucide-react/dist/esm` error that blocked the first v0.5.0 deploy attempt)
  cannot stall the build step and leave the deploy script mid-way through
  `set -euo pipefail`.
## [0.5.0] — 2026-06-30


### Added

- **Data gap healer — full-coverage audit + heal + nightly backfill.** A
  resumable, budget-aware service that accounts for **every** recorded `uw_scan`
  table (118 datasets) and repairs safe coverage gaps. New `data_gap_*` domain
  (`migration 092`): a dataset registry (one source of truth in
  `reports/data_gap_healer.py`, projected to `data_gap_dataset_registry`),
  gaps-only `data_gap_items`, resumable `data_gap_runs`, and no-data
  `data_gap_caveats`. The exact scanner finds per-ticker/date misses by
  set-difference SQL (zero provider calls); the heal dispatch maps each healable
  dataset to an existing production job via one of four strategies
  (`run_once` / `run_once_lookback` / `per_ticker_range` / `per_ticker_date`).
  CLI `scripts/backfill/data_gap_healer.py` exposes `audit` / `execute` /
  `resume` / `verify` / `verify-all`; every run writes a Markdown+JSON report
  under `output/data-gap/`. **Full coverage includes macro/FRED/rates/gold**
  (healed by re-running their idempotent ingest jobs over a lookback window).
  A nightly job (`DATA_GAP_HEALER_ENABLED`, default off) runs at 20:00 ET — just
  after the UW quota reset — under an advisory lock, capping **only** UW spend
  (`DATA_GAP_HEALER_MAX_UW_CALLS`, default 20000); Massive/external are
  uncapped. `/api/health` gains a `gap_healer` block. Policy matrix:
  `docs/runbooks/data-gap-dataset-policy.md`; runbook:
  `docs/runbooks/data-gap-healer.md`.
- **YTD historical backfill from UW (`/volatility/stats`, `/volatility/realized`).**
  `realized_volatility_history` + `volatility_stats_history` are UW-sourced, not
  derived — repointed off the rollup adapter (which only writes
  `vrp_daily`/`stock_analytics_daily`) to dedicated heal adapters:
  `realized_volatility` (full ~1y series, 1 call/ticker) and `volatility_stats`
  (one row per ticker/date via `?date=`, the YTD `vol_stats` backfill — that
  table only accumulated forward from its 2026-05-11 inception because the
  fetcher was current-snapshot-only). `fetch_volatility_stats` gains an optional
  `market_date` selector (current-snapshot default preserved).
- **Watchlist ticker lifecycle log** (`migration 093`,
  `watchlist_ticker_events`). `reconcile_watchlist_lifecycle` (run nightly + CLI
  `reconcile`) diffs the live watchlist vs the last-known state: **added/re-added**
  tickers are logged and backfilled by the same run's audit; **removed** tickers
  are logged with their rows left intact (no exclusion code needed — the
  denominator is the live watchlist, so they already drop out). Append-only, so a
  remove→re-add cycle keeps the full history.
- **Benchmark snapshots persist through a heartbeat clock race.**
  `scheduler_heartbeat_lag_seconds` is clamped to `max(0, …)` in
  `benchmark/collector.py` so a heartbeat landing a hair after `now_utc` no
  longer violates the `058` `>= 0` CHECK and drops the snapshot
  (`pipeline_benchmark_snapshots` was stuck at 0 rows).

### Fixed

- **Gap-healer trading-day calendar (kills weekend/holiday phantom gaps).**
  `_calendar_dates` unioned the dataset's own dates with the `market_tide`
  reference, so a stray weekend/holiday price-bar in a dataset leaked that
  non-trading day into its own expected calendar — manufacturing a full-watchlist
  phantom gap for every ticker missing that bar. The reference
  (`market_tide_sentiment_daily`) is a clean trading-day spine (0 weekend/holiday
  rows), so it is now the sole calendar. On real prod data this cut the gap count
  25,814 → 15,021; `vrp_daily`/`realized_volatility_history`/`stock_analytics_daily`
  collapsed from ~3,000–3,800 phantom gaps each to the 2 genuine misses each.
- **Resume recovers items orphaned by a killed run.** A timed-out/killed run left
  items stuck `running`, which `claim_next_items` skips; `resume` now requeues
  them to `planned` first (heals are idempotent, so a blanket requeue is safe),
  so a backfill actually continues where it left off.
## [0.4.1] — 2026-06-30


### Changed

- **Market Tide spot overlay uses xenon IB bars as the primary source** (Apex
  REST is the automatic fallback). `sources/apex.py` now tries
  `POST /historical/bars` against xenon's query API (`XENON_QUERY_API_URL` /
  `XENON_QUERY_API_KEY`) before falling back to the Apex lake endpoint. Requires
  xenon ≥ v0.7.3 (moremeds/xenon#169 — fixes `_bar_date_to_iso` truncating
  intraday timestamps to date-only).
## [0.4.0] — 2026-06-30


### Added

- **Market Tide tab — Top Net Impact chart with per-update rank change.** New
  panel beside the daily tide (UW `/market/top-net-impact`): horizontal diverging
  bars of market-wide net option premium (`net_call − net_put`) per ticker,
  bullish/bearish split. Each capture carries `prev_rank` into the next so the
  chart shows ▲/▼/• rank movement between updates. Captured every 15 min RTH
  (`regime_top_net_impact_scan`, uw-0, kill switch `TOP_NET_IMPACT_CAPTURE_ENABLED`);
  migration `090`; storage `top_net_impact_repository.py`; endpoint
  `/api/regime/top-net-impact`.
- **Tide slope/sentiment ("TIDE SENTIMENT").** Quantifies the UW Daily Market
  Tide guide: spread `S = NCP − NPP`, its session + 30-min slope, divergence
  (`trend_strength = |net displacement| / range`), driver (call/put buying/selling),
  momentum, and net-volume confirmation. Surfaced live on `/api/regime/market-tide`
  (`sentiment` block) + a banner in the tab. EOD-persisted per session for
  backtesting (`market_tide_sentiment_daily`, migration `091`; nightly
  `market_tide_sentiment_eod` @16:25 ET). `reports/market_tide_sentiment.py`.
  `macmini-prod.sh` seeds the full stored-bar history once at deploy time
  (`market_tide_sentiment_backfill.py --if-empty`, best-effort, no UW budget),
  so the backtest dataset is complete the moment the feature ships; later
  deploys skip it (seeds only when the table is empty).
  Forward-return probe (`scripts/research/tide_slope_backtest.py`,
  `docs/research/tide-slope/`) finds it **descriptive, not predictive** at the
  daily horizon (n=120 YTD: ~50% hit, |corr| below the significance bar).
- **Apex SPY-spot overlay for the tide chart.** `sources/apex.py` reads SPY 5-min
  closes from the Apex bars API; `scripts/backfill/market_tide_spot_backfill.py`
  joins them onto `market_tide_snapshots.spot` by UTC instant so the historical
  SPY gold line renders (UW tide carries no price).

### Changed

- **Market Tide tab redesigned + default regime tab.** Daily chart now follows
  the UW layout — compact stats line (`SPY · Vol · NPP · NCP`), `Net Premiums` /
  `Net Volume` band labels, SPY on the left axis, premium + baseline-0 volume on
  the right, date-first time axis — wrapped (with Top Net Impact) in a single
  titled container carrying the UW guide tooltip. Clicking **Regime** now defaults
  to **Market Tide** (was Gamma Exposure).
- **`market-tide` / `top-net-impact` fetchers treat UW 422 (future EST date) as
  no-data**, like 400 — so a backfill walking from "today" (still future in ET)
  skips cleanly instead of crashing.
- **VRP macro entry-capture now stores IB's native option greeks as the primary
  source.** `xenon_query.fetch_ib_option_quote` previously discarded the
  delta/gamma/vega/theta in the `/options/greeks` response and `quote_leg` always
  BS-computed greeks from the marked IV. The IB-native greeks (which reflect IB's
  live surface) are now consumed as primary, rescaled to argon's BS column
  convention — vega ×100 (IB per-1% vol → per-100%) and theta ×365 (IB per-day →
  per-year); delta/gamma already match. BS-from-IV remains the backup when IB
  returns no greek set (UW-fallback legs, or IB without greeks). Adds `'ib'` to
  the `greeks_source` tag (`VrpMacroEntryLeg.greeks_source` contract widened to
  `ib | bs | none`).
## [0.3.6] — 2026-06-25


### Fixed

- **Macro short-vol "Tracked entry" showed fabricated strikes/mids.** Pre-birth
  (no cohort captured today), the entry preview fell back to `_bs_indicative_legs`
  — a synthetic 5-pt SPX strike grid (e.g. 7095/7090, which aren't listed strikes)
  priced with flat-vol Black-Scholes, rendered in the card as if they were market
  quotes. A fake number is worse than none. Removed the synthetic path entirely:
  the `/vrp-macro-signal/entry/preview` endpoint now serves persisted-cohort legs
  (real strikes + NBBO) or **empty legs** with no fabricated ETD — the card shows
  "No entry preview yet" / "ETD —" until a real cohort exists. Pairs with the
  grid-cache fix below, which is what lets a real cohort actually get born.

- **VRP macro entry-capture never persisted** — the daily SPX auto-birth
  (`_birth_auto`) enumerated the listed strike grid via two live UW calls inside
  the 10:00–15:00 ET birth crons, but the UW daily quota is reliably exhausted by
  ~08:00 ET, so every birth 429'd and aborted (`vrp_macro_entry` /
  `vrp_macro_entry_quote` stayed empty; the preview card silently fell back to the
  BS-`modeled` indicative legs). Added a nightly `vrp_macro_entry_grid_refresh`
  job (03:50 ET, massive-0, when the UW budget is fresh) that caches the real
  UW-listed expiry + put strikes into a new `vrp_macro_entry_grid` table
  (migration 088). The unattended auto-birth now reads that cache and makes **zero
  UW calls**, so an exhausted daily quota can no longer abort it; the on-demand
  Capture button reads the same cache (UW-free whenever the cache is warm, i.e.
  after the first nightly refresh — a cold-cache click still falls back to a live
  UW lookup). The cache read reuses the most-recent prior day's real grid (within
  a 4-day staleness bound, chosen expiry still open) if a nightly refresh is
  missed, rather than skipping birth. As part of this, `_uw_chain_strikes` now
  closes its `scan_runs` row as `failed` on a UW error instead of leaving it stuck
  in `running` (the visible side-symptom of the original bug).
## [0.3.5] — 2026-06-25


### Fixed

- **#180 — `option_intraday_buckets` covered only ~half the watchlist.** The
  intraday OI-mover refresh is registered on the primary UW worker only, but it
  still passed the per-worker crc32 shard filter — so ~55 shard-1 tickers
  (TSLA/NVDA/MSFT/GOOGL/META/AVGO …) were fetched by nobody and their stock-page
  TAPE column stayed permanently blank. The job now covers the full watchlist
  (`ticker_filter=None`; single-flight is already enforced by its advisory
  lock), and emits per-outcome counters (`skipped_no_run`, `skipped_no_movers`,
  `contracts_empty`, `contracts_error`) so a future coverage gap self-reports.
  One-shot backfill: `scripts/backfill/intraday_buckets_backfill.py`
  (budget-gated) — `--missing` auto-targets the blank set, and `--since` sweeps
  the full per-session history (`backfill_intraday_history`, distinct advisory
  lock) bounded by our recorded `oi_change_events` sessions, not just the latest
  run. Roughly doubles this job's daily UW calls; `UwClient` throttle/retry
  absorbs transient 429s.
- **#179 — single-name `greek_exposure_daily` froze at 2026-05-20.** It is
  index-only by design (the regime GEX scan only covers `gex_scan_tickers`); the
  100 single-name rows were a one-off backfill tail with no recurring writer. A
  new nightly job (`greek_exposure_daily_refresh`, 18:30 ET, uw-0) fetches UW's
  aggregate `/greek-exposure` history per single-name ticker — the SAME
  authoritative basis the indices use. (A DB→DB per-strike sum was tried first
  but validation showed it 20–134% off the aggregate — a partial-chain proxy —
  so it was dropped.) Backfill:
  `scripts/backfill/greek_exposure_daily_refresh_backfill.py` (UW, `--confirm`).

### Added

- **Data-date freshness monitor (prevention).** A nightly job
  (`data_freshness_monitor`, 21:00 ET) records, per curated per-ticker table,
  the newest **data date** + scope-aware active-watchlist coverage into
  `data_freshness_snapshots`, flags freezes, WARN-logs, and surfaces a
  `freshness` block on `/api/health` (all DB-up returns). Complements
  `list_record_health`, which keys on write-timestamps and skips no-timestamp
  tables (e.g. `greek_exposure_daily`) — the blind spot that let the vrp/greek
  freezes slip for five weeks. Migration `087`.
## [0.3.4] — 2026-06-25


### Fixed

- **`vrp_daily` silently froze for ~90% of the watchlist** (2026-05-22 onward).
  UW's realized-volatility endpoint began returning `null` for the
  `realized_volatility` column while `price` + `implied_volatility` stayed fresh;
  the nightly `nightly_vol_analytics_rollup` fed the raw null RV into
  `compute_vrp_series`, so `vrp = iv − rv` was `NaN` and `persist_vrp_daily`
  wrote nothing (the same loop's RV-independent `stock_analytics_daily` kept
  updating, masking the gap). The rollup now applies `_fill_rv_from_price` —
  deriving RV from the fresh price column, the same convention the stock-page
  read path already used — before computing VRP. Added
  `scripts/backfill_vrp_daily.py` (pure DB→DB, zero UW calls, idempotent) to
  recover the historical gap; one run restored `vrp_daily` from 9 → 104/104
  active tickers fresh. Regression test added in
  `tests/integration/worker/test_volatility_jobs.py`.
## [0.3.3] — 2026-06-24


### Added

- Per-stock **Short-Vol card** on the stock page's Market Structure tab — the
  single-name sibling of the SPX Macro Short-Vol card, placed third on the
  Directional-Bias row. A TRADE/SKIP sell-premium readout derived at read time from
  the latest persisted `vrp_daily` row (no new endpoint, job, or migration): TRADE
  only when vol is rich (`vrp_z_20 ≥ 1.0`), the ticker's sector is in the sellable
  set (`vrp_gate`), and a known next-earnings date is clear of the ~45-day hold
  window; otherwise SKIP with a reason (`vol not rich` / `sector vol not sellable` /
  `earnings inside hold window` / `earnings date unavailable`). On TRADE it models the
  same flat-vol bull put spread (0.25Δ short / 0.125Δ wing, ~30-day hold) as the macro
  signal, reusing `size_weight` + `build_bull_put_spread`; macro/ETF classes skip the
  earnings gate (they don't report), mirroring `vrp_gate`'s asset-class split.
  Non-finite `vrp_z_20` (short-history NaN) is normalized away, and the build is
  wrapped so the card can never take down the stock page. New
  `reports/stock_short_vol.py`, `StockShortVol` model + `SingleStockReport.short_vol`,
  and `web/components/stock/panels/ShortVolPanel.tsx`. EOD basis (modeled off the
  EOD-close spot). Plan `docs/superpowers/plans/2026-06-24-stock-short-vol-card.md`.
## [0.3.2] — 2026-06-24


### Added

- VRP macro **forward entry-capture & markout recorder**: records the real forward
  NBBO + greeks of the SPX bull-put-spread the Macro Short-Vol signal would place,
  tracked daily to expiry. A daily-born `auto` cohort (the 4 put contracts bracketing
  the 0.25Δ short / 0.125Δ wing at ~43-cal-DTE) is snapshotted **8×/day** (10:00–15:00
  ET hourly + 15:55 EOD + 16:10 post-close), tapering to EOD-only after 30 calendar
  days. Each leg quotes **xenon/IB-primary** (true NBBO + IV) → **UW fallback** →
  **greeks always BS-computed** from the marked IV (one-model: IB theta is per-day, BS
  per-year — never mixed). New table pair (`vrp_macro_entry` + `vrp_macro_entry_quote`,
  migration `085`), `reports/vrp_macro_entry.py`, `worker/jobs/vrp_macro_entry.py`
  (massive-0, gated by `vrp_macro_entry_capture_enabled`), and
  `GET/POST /api/regime/vrp-macro-signal/entry/{preview,capture}`. The Macro Short-Vol
  regime card gains a strike/ETD preview panel (served from the persisted snapshot —
  zero IB, zero new UW) + a one-click Capture button; the "(gate at 0)" / "stand aside"
  copy is dropped. Live-verified against prod IB (3/4 legs `source=xenon_ib`). Also
  fixes the stale `xenon_query_api_url` default (`:8421`, which was dead → silently
  no-op'd the surface IV canary too) to the mini's authenticated `:8321`; deploy must
  set `XENON_QUERY_API_KEY` in the mini's argon `.env` or the IB path falls back to UW.
  Plan `docs/superpowers/plans/2026-06-24-vrp-macro-entry-capture.md`.
- GOAS put-write delta sweep (research): a self-contained study finding the short-put
  **delta + tenor sweet spot** for the Goldman Options Advisory Strategy (systematic
  always-on OTM index put-writing). Three new `reports/` modules —
  `goas_putwrite_pricing.py` (a parametric downside-skew layer `iv(K)=atm·(1−slope·ln(K/S))`
  calibrated to GOAS's one published quote: 2026-05-05 SPY 96.2%-strike / 0.700%-premium →
  slope 2.693, with flat-vol as the conservative floor), `goas_putwrite_account.py` (a
  laddered, defined-risk **cash-secured** put-write NAV book — held to expiry, intrinsic
  settlement, fair-value daily marks, collateral earning the risk-free per CBOE PUT-index
  convention — plus `curve_metrics`/`putwrite_metrics` and a SPY buy-hold benchmark), and
  `goas_putwrite_sweep.py` (delta×tenor×pricing×fee sweep with regime slices and a
  per-regime catastrophe-gated ranking; management fee modeled as a downstream NAV drag,
  copying GOAS's own fee framing). Runner `scripts/research/goas_putwrite_run.py` reads SPY+VIX
  daily closes directly from the market-warehouse lake (2006→, ~20.4y, no Postgres/network)
  and writes five full-trace artifacts + a master findings note under
  `docs/research/goas-putwrite/`. Headlines: gross Sharpe rises monotonically with delta but
  short (21d) weekly writing fails catastrophically in fast crashes (COVID Sharpe −1.6) — the
  binding constraint is **tenor, not delta**; net-of-1%-fee gated sweet spot is **0.30Δ/63d**
  (Sharpe 0.147), conservative pick **0.15Δ/63d** (Sharpe 0.108, maxDD −14%, 95% win-rate).
  Every unlevered cash-secured cell trails SPY buy-hold risk-adjusted (best 0.15 vs 0.34) but
  at 2–4× smaller drawdown — the premium harvest above cash is only ~0.5–1.4%/yr, so GOAS's
  3–6% net target requires the 20–40% leverage this defined-risk study excludes. Reproduce:
  `uv run python scripts/research/goas_putwrite_run.py`.
## [0.3.1] — 2026-06-23


### Added

- VRP backtest iteration 4 (research): robustness suite on the SPX macro short-vol
  WINNER — `reports/vrp_robustness.py` (min viable capital, SPY buy-and-hold benchmark,
  geometric compounding metrics, weekday sweep, bear-start study, and a seeded
  Monte-Carlo suite: entry-timing jitter, stationary block bootstrap, randomized
  start incl. a GFC-windowed variant, config perturbation) plus six backward-compatible
  flags on the `vrp_capital_account` ledger (compounding, entry-weekday, entry-jitter,
  staggered extra tranche) that reconcile byte-for-byte to the iteration-3 path when off.
  Runner `scripts/research/vrp_robustness_run.py` writes seven `iter4-*.csv` full traces
  (per-config + per-trial Monte-Carlo + long-form bear-start equity path); findings in
  `docs/research/vrp/vrp-backtest-iteration-4-findings.ipynb` + an Iteration-4 section of
  the master report. Every experiment benchmarked against the iteration-3 SPX base case
  and SPY buy-and-hold. Headlines: the staggered extra tranche marginally beats the base
  (Sharpe 1.71 vs 1.68) while the contract overlay is exposure-not-edge; entry weekday
  matters modestly (1.33–1.53, all below the 1.65 stride); starting at a bear top still
  earns +150–180% over 36m; and config-perturbation p5 Sharpe 1.05 shows the result is
  not a knife-edge overfit. SPX vol-selling is six-figure-capital (one spread's max-loss
  rises ~15× to ~$28k by 2026).
- VRP capital-utilisation backtest (research): new `reports/vrp_capital_account.py`
  — a single shared **$50k cash-account ledger** (`CapitalConfig`,
  `desired_contracts`, `simulate_account`, `account_metrics`) that *reuses* the
  validated macro short-vol `WINNER` engine to measure annualised return, capital
  utilisation, skip/fill rates, Sharpe and max-drawdown on a real dollar account
  (integer contracts floored to a risk-% of capital, capital-capped with logged
  skips). Reconciles exactly with `backtest_laddered` (Δ Sharpe 0.000). Adds SPY
  to macro `INDEX_SPECS`, a sweep runner (`scripts/research/vrp_capital_sweep.py`)
  with full-trace CSVs, and an executed findings notebook + verdict/master report
  under `docs/research/vrp/` (single-name SPX beats the 3-name blend; the overlay
  is leverage not edge; compounding sweet spot ≈ stop at 4–8×). New `research`
  dependency group (matplotlib/nbconvert/ipykernel) for the notebook only.
- Option-surface historical backfill: `option_surface_backfill` function and
  `scripts/option_surface_backfill.py` runner seed `option_surface_grid_daily`
  for up to 30 past trading days in one shot. UW `/greek-exposure/expiry` and
  `/greeks` both accept an optional `date=` param (now forwarded by the fetchers);
  dates already in the table are skipped. Run promptly after first deploy — UW
  403s beyond ~30 trading days.

### Fixed

- `reports/vrp_macro_drawdown._lake_spot` now skips lake rows with a null
  `trade_date`. SPY's equity-lake parquet carries ~73% null-date rows (an
  alternate-schema partition); without the guard `load_index_vol("SPY")` raised
  `TypeError` on the `d >= start` comparison. No-op for symbols with clean dates
  (QQQ/IWM).


## [0.3.0] — 2026-06-23


### Added

- Option-surface capture: a nightly, forward-accumulating per-strike IV/greeks
  grid for every watchlist ticker (`option_surface_grid_daily`, migration 077),
  plus an ATM IB-vs-UW IV canary (`iv_source_validation`, migration 078). New
  `option_surface_capture` job (19:00 ET) and `option_surface_iv_canary` job
  (19:30 ET) on the uw-0 worker, Mon–Fri. Enumerates the full term structure via
  `greek-exposure/expiry` — not `/option-contracts`, which UW silently caps at
  500 contracts by volume and so drops long-dated expiries (measured: SPX 28/53
  missing). One `/greeks` call per expiry, idempotent upsert, per-ticker failure
  isolation. The surface only accrues forward: UW returns 403 for per-strike
  history beyond ~30 trading days, so every uncaptured night is permanently lost.
## [0.2.3] — 2026-06-22


### Fixed

- Release pipeline no longer wedges the mac-mini auto-deploy on `uv.lock` drift.
  `cut.sh prepare` now re-locks `uv.lock` so its editable self-version tracks the
  version bump and commits it with the release, and `version_sync_check` (run via
  system `python3` before `uv sync` in CI, so a stale committed lock can't be
  auto-repaired and hidden) fails the build if the lock self-version ever drifts
  from `VERSION` again. Previously the committed lock lagged the bump; the first
  `uv run` on any host rewrote that one line, dirtied the tree, and the deploy
  poller refused every deploy — silently pinning prod to the last-deployed
  release (the mini sat on v0.1.2 for 4 days while v0.2.0–v0.2.2 published).
## [0.2.2] — 2026-06-22


### Added

- VRP macro signal deploy slice: nightly persistence + read API for the promoted bull-put-spread signal shipped in 0.2.1. New `vrp_macro_signal_daily` table (migration 083), `vrp_macro_signal_refresh` job (03:45 ET, Mon–Fri, primary worker — runs SPX/QQQ/IWM weekly readout + `backtest_laddered` headline and persists one row per name per snapshot date, with per-name failure isolation), and `GET /api/regime/vrp-macro-signal` returning the latest signal per name. Closes the persist-every-research-trace gap for the VRP macro engine.
## [0.2.1] — 2026-06-22


### Added

- VRP macro signal engine (`reports/vrp_macro_signal.py`): promoted bull-put-spread winner config (Δ0.25 short, ramp+ vrp-z sizing, 30 trd-day hold) into first-class engine code with `WINNER` constant, `backtest_laddered` (SPX Sharpe 1.65 / QQQ OOS 1.00), and `current_macro_signal` weekly readout (TRADE/SKIP + modeled strikes/credit/max-loss)
- VRP macro research expansion (`reports/vrp_{candidates,backtest,directional,harvest_axes,gate,rv_validation}.py`): corrected-measurement engine, sector/horizon/directional/ΔVRP sweep axes, per-ticker iron-condor candidates, paper ledger, model-repriced weekly backtest
- Corporate actions refresh job (nightly 17:35 ET) for exact-RV split/dividend adjustment
## [0.2.0] — 2026-06-21


### Added

- VRP harvest markout (`reports/vrp_markout.py`, migration `079_vrp_harvest_verdicts`,
  `GET /api/regime/vrp-harvest`): scores whether selling rich vol (`vrp_z ≥ +1`) earns a
  reliable, positive premium per `(asset_class, deviation_class)` bucket. Reuses the skew
  engine's out-of-sample discipline — time-ordered walk-forward holdout plus a per-quarter
  catastrophic-degradation gate — over the existing `vrp_daily` panel, and excludes any
  forward window spanning a (flow-event-reconstructed) earnings date. Verdicts
  (`HARVEST_SELLABLE` / `NONE`) persist nightly at 18:50 ET (massive-0 worker) to
  `vrp_harvest_verdicts`; the RICH−CHEAP spread is recorded so a flat (no-edge) result
  stays legible.
## [0.1.2] — 2026-06-18


### Fixed

- Stock detail pages (Flow / Market Structure / GEX) no longer render empty
  during US off-hours. `Repository.latest_run_id` selected the newest scan_run
  via a hand-maintained `notes` denylist; the skew engine's `skew_swing_greeks`
  side-channel runs were not on it and — having higher run_ids and no aggregates
  — shadowed the real `full_scan`, blanking every ticker's detail page after
  ~17:30 ET each day. The selector (and the `get_scan_duration_summary` health
  metric) now key on the property the report actually needs —
  `status='ok' AND aggregates IS NOT NULL` — so no future side-channel job can
  re-break it. No data was lost; the fix is read-path only.
## [0.1.1] — 2026-06-17


### Added

- Health sidebar now shows deployed backend version in the collapsed header,
  sourced from the running process via the existing `/api/health` poll.
## [0.1.0] — 2026-06-17

### Added

- Baseline release. Per-ticker options analytics: Next.js web (`web/`, :3001),
  FastAPI read API (`src/uw_scan/api/`, :8400), and the APScheduler worker, over
  a single Postgres (`uw_scan` schema). Scanner, regime (CRI/GEX/VCG), skew,
  Gold Compass, cockpit, and Trade Insights AI (Codex/Claude/DeepSeek) ship in
  this baseline. First release cut through the tag-driven `release.yml` pipeline.
