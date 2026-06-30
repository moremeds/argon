# Data Gap Healer Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Turn Argon's current ad hoc backfill scripts and freshness checks into a full, resumable, budget-aware data-gap healer that accounts for every recorded dataset and can audit, plan, execute, and verify safe coverage repairs.

**Architecture:** Build on `feat/data-quality-coverage`: keep the existing `data_freshness_snapshots` monitor as the coarse freeze detector, then add a stricter `data_gap_*` domain for exact ticker/date/session gap items, execution state, budget state, and no-data caveats. Every table with date/time state is represented in a registry; each row declares whether it is strict-healable, freshness-only, operational/provenance, research output, or intentionally excluded. Healable datasets get small adapters that reuse the production writer path or an existing backfill job; the healer orchestrates adapters but does not invent second write semantics.

**Tech Stack:** Python 3.13 via `uv`, psycopg 3, Postgres schema `uw_scan`, APScheduler job registration behind an opt-in flag, pytest + pytest-postgresql, UW/Massive clients already in `uw_scan.sources`.

---

## Eng-Review Outcome (2026-06-30) — Revised Scope & Task Plan

> This block is canonical and **supersedes any conflicting detail in the per-task sections below**. Decisions from `/plan-eng-review`.

**Decisions taken:**

1. **Scope = option B (full coverage, collapsed adapters).** Keep audit + heal coverage for every registered dataset, but implement healing as ONE dispatch table over existing jobs — not ~13 bespoke adapter classes + a standalone budget module + a separate full-service scheduler.
2. **Base rebased onto `main` (head `091`).** The worktree was reset to `main` (`7cc356df`); the 12 prior commits (data_freshness, #179, #180) are already in main byte-identical, so they were dropped as redundant (still reachable via `feat/data-quality-coverage`). New migration is `092_data_gap_healer.sql`. The four previously-missing registered tables (`vrp_macro_entry_grid` 088, `market_tide_snapshots` 089, `top_net_impact_snapshots` 090, `market_tide_sentiment_daily` 091) now exist locally and in the test DB.

**Heal dispatch architecture (replaces the adapter-class design):**

- `DATASET_REGISTRY: dict[str, HealSpec]`. `HealSpec` is a record (dataclass), not a class hierarchy:
  - `dataset, audit_mode, date_col, ticker_col, expected_frequency, provider (uw|massive|external|db|none)`
  - `granularity: run_once | run_once_lookback | per_ticker_range | per_ticker_date`
  - `heal: Callable | None` — invokes an EXISTING job/backfill; `None` for freshness_only / provenance / excluded
  - `verify: Callable` — strict `COUNT(*)` in the target table **at the item's own `data_date`**
- `execute` loop dispatches on `granularity`:
  - `run_once` → `nightly_vol_analytics_rollup(repo)`, `refresh_eod_sentiment(repo, sessions=…)`
  - `run_once_lookback` → re-run an idempotent ingest job with a lookback covering the gap window. **This is how macro/FRED/rates/gold heal:** `gold_fred_ingest_job(dsn, lookback_days=N)` (writes `macro_series_daily`/`macro_series_monthly`), `rates_fred_ingest_job(dsn, fred_api_key, lookback_days=N)` (writes `rates_*`), and the `gold_*_ingest_job(dsn, lookback_days=N)` family (GPR/ETF-holdings/spot/COMEX/CFTC-COT/LBMA/WGC-CB) + `gold_posture_compute_job`. All are `ON CONFLICT` idempotent. `lookback_days = clamp(today − earliest_gap_date)`.
  - `per_ticker_range` → `MassiveOhlcProvider.fetch_daily(t, lo, hi)`
  - `per_ticker_date` → `option_surface_capture._build_ticker_rows` + `repo.upsert_option_surface_grid`
- **Provider buckets / budgets** (full coverage, intention restated 2026-06-30: macro/FRED included; **only UW is capped**):
  - `uw` — option surface, greek exposure, market-tide/top-net, intraday buckets, `gold_uw_options_daily` → hard-capped by `DATA_GAP_HEALER_MAX_UW_CALLS` (the only scarce resource).
  - `massive` — `daily_ohlc` → **uncapped** (paid feed, no per-day quota that matters here).
  - `external` — FRED / CFTC / Treasury / LBMA / COMEX / WGC / GPR (free, self-throttling sources) → **uncapped**. Healed without touching the UW cap.
  - `db` — vol rollups, sentiment, vrp/analytics, `gold_posture_daily` → no budget (DB-to-DB).
- Budget guard reads existing UW rate state (daily/minute, as the live backfill already logs) before each UW spend; non-UW buckets are unbounded (the source clients self-throttle). Over-UW-cap → mark `skipped_budget`, resume next night; never crash.

**History depth (intention restated 2026-06-30: get as much history as possible):**

- The audit window is NOT a short rolling lookback. It runs from `DATA_GAP_HEALER_START` (default `2026-01-01`, configurable earlier) to today, and each heal goes back as far as the source serves.
- Per-source depth is bounded by the registry `retention_days` (a heal hint, not a hard stop): `None` = attempt full history and let an empty provider response become honest `no_data`; a number = don't waste calls past it. Massive OHLC and FRED/gold/rates serve years; UW option/greek history is finite, so old dates settle to `no_data` once.
- Calendar for deep history (T3): expected sessions = the union of dates already present in the dataset across all tickers within the window (self-calendar), plus the `market_tide_sentiment_daily` reference calendar where it overlaps. Finds per-ticker holes in any period the table has any data, with zero provider calls.

**Heal-capability flags (verified signatures, do not assume historical repair works):**

- `refresh_eod_sentiment(repo, *, sessions=1)` heals only RECENT sessions → an old `market_tide_sentiment_daily` gap returns `no_data` reason `derive_window_exceeded`.
- `greek_exposure_daily_refresh` UW aggregate returns the CURRENT snapshot → only same-day gaps heal (the 2026-06-29 2/103 case if run same-day); past dates → `no_data` reason `provider_no_history`.

**Persistence / perf:**

- `data_gap_items` stores ONLY gap (missing) rows, never the full expected cartesian product (a full YTD strict audit is ~103 tickers × ~123 sessions × ~25 datasets ≈ 300k pairs). Per-`(run, dataset)` coverage totals go in `data_gap_runs.summary_jsonb`.
- Coverage computed with ONE set-difference query per dataset (expected calendar × eligible tickers `EXCEPT` actual), not per-ticker Python loops (that is an N+1 against Postgres).

**Benchmark fix (was Task 10):**

- Keep the `scheduler_heartbeat_lag_seconds >= 0` CHECK (`058` migration:34) — it is correct, lag is never legitimately negative. Fix the PRODUCER: clamp `max(0, …)` in `benchmark/collector.py:95` + regression test. **Drop migration `093`** — no constraint change.

**Scheduler (collapses old Tasks 9 + 18) — automated nightly capped backfill:**

- ONE kill-switched job (`DATA_GAP_HEALER_ENABLED`, default `false` until proven, then flip on) at **20:00 `America/New_York`** — just after the 00:00 UTC UW daily-quota reset (= 8pm EDT), so it draws on fresh quota. The existing 19:00/19:30 ET option-surface capture runs *before* reset on the old day's budget, so they don't collide.
- It runs `audit` then `execute` over `DATA_GAP_HEALER_DATASETS` (**default empty = all healable datasets — full coverage incl. macro/FRED/rates/gold**) from `DATA_GAP_HEALER_START` (default `2026-01-01`) to today — **as much history as possible**. Only UW is capped, by `DATA_GAP_HEALER_MAX_UW_CALLS` (default **20000**, configurable); Massive + external buckets are uncapped. The 20k UW cap reserves a third of the 60k daily quota; UW gaps beyond the cap become `skipped_budget` and resume the next night until history is filled. The audit gates every heal, so monthly/weekly tables only spend a call when a period is genuinely missing.
- Advisory lock + a guard that **skips if a manual UW backfill (e.g. PID-75761-style) or a prior healer run is still `running`**, so it never fights an in-flight backfill. Over-cap items → `skipped_budget`, picked up the next night or via `resume`.
- After every run (scheduled or manual) it writes the **report artifact** and refreshes the `/api/health` `gap_healer` block.

**Report (intention #2):**

- `verify-all` / every `execute` writes `output/data-gap/<YYYY-MM-DD>-gap-report.md` (human-readable) **and** `.json`, containing: per-dataset before/after strict coverage, healed / no_data / skipped_budget counts, the no-data caveats with reasons, UW+Massive requests actually spent, and the exact reproduce command. The DB (`data_gap_runs` + gaps-only `data_gap_items`) is the durable source; the artifact is the readable view.

**Revised task list (supersedes the 19-task numbering below):**

| New | Was | Scope |
|-----|-----|-------|
| T1 | 1 | Specs + registry dataclasses, `audit_mode`, `eligible_tickers_for_date`, discovery |
| T2 | 2 | Migration `092` + repository (runs/items/caveats/registry; **items = gaps-only**; seed registry + SPCX caveat) |
| T3 | 3 | Read-only scanner + `audit`/`--discover` CLI (set-difference SQL; zero provider calls) |
| T4 | 4,5,6,7 | Heal dispatch: `HealSpec` registry + 3 granularity strategies + budget guard + verifiers; reuse existing jobs |
| T5 | 8,17 | CLI `execute`/`resume`/`verify` + `verify-all` evidence export |
| T6 | 13 | Full dataset policy matrix doc generated from the registry + policy test |
| T7 | 14,15,16 | Register + verify remaining families (core options, derived vol/VRP/skew, regime/gold/rates/macro) — registry rows + verifiers + no-data/freshness policies, **no new writer code** |
| T8 | 10 | Benchmark producer clamp + regression test (**no migration**) |
| T9 | 11 | Health `gap_healer` block + OpenAPI snapshot |
| T10 | 9,18 | One opt-in kill-switched scheduler job + safety guards |
| T11 | 12 | Runbook + CHANGELOG |
| T12 | 19 | Macmini full dry-run audit + one DB-to-DB execute, evidence doc |

**Tests (consolidated):** one parametrized `test_data_gap_healers.py` over registry entries + 3 strategy tests + verifier SQL tests, replacing the 6 per-pack files. Plus: registry-acceptance (zero unregistered), SPCX caveat (excluded 06-16, included 06-17), **strict-vs-freshness divergence regression** (2026-06-29 greek_exposure: strict shows the gap while freshness shows 100%), negative-heartbeat-lag regression, budget-exhaustion (zero provider calls in dry-run).

---

## Current Evidence

Collected against macmini Postgres `100.66.147.98/option_wizard`, schema `uw_scan`, on 2026-06-30 11:39-11:41 HKT.

### Branch / Codebase State

- Worktree for implementation: `.worktrees/data-gap-healer`
- Branch: `feat/data-gap-healer`
- Base branch: `feat/data-quality-coverage` at `8e3fdc73`
- Baseline verification in the worktree:
  - `UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/reports/test_data_freshness.py tests/integration/storage/test_data_freshness_repository.py -q`
  - Result: `6 passed in 1.15s`

`feat/data-quality-coverage` already adds:

- `src/uw_scan/reports/data_freshness.py`
- `src/uw_scan/storage/data_freshness_repository.py`
- `src/uw_scan/worker/jobs/data_freshness_monitor.py`
- `src/uw_scan/storage/migrations/087_data_freshness_snapshots.sql`
- `scripts/backfill/intraday_buckets_backfill.py`
- `scripts/backfill/greek_exposure_daily_refresh_backfill.py`

That branch monitors freezes and exposes health. It does not yet persist exact gaps, budget-aware healing runs, no-data exceptions, or adapter-level verification.

### Live DB Coverage Snapshot

Active watchlist denominator: 103 tickers. `SPCX` must be excluded before 2026-06-17.

Full schema inventory was also run against every `uw_scan` table with date/time columns, sorted by size. The first draft's hand-picked list covered the immediate warm-store gaps but did **not** cover everything Argon records. This plan now requires a recorded-dataset registry: every table with a time/date column must be explicitly classified as strict-healable, freshness-only, provenance/audit, operational state, research artifact, or intentionally excluded with a reason.

Strict YTD gap scan, using `market_tide_sentiment_daily.data_date` as the session calendar:

- `option_surface_grid_daily`: 27 gap days, 2587 missing ticker-date pairs while the live targeted backfill is running.
  - Still full missing: 2026-04-20..2026-05-11, 2026-06-11..2026-06-18, 2026-06-23..2026-06-24, 2026-06-29.
  - 2026-06-10 improved during the current run from 13/102 to 72/102.
  - 2026-06-22 still missing KORU/SOXL.
- `daily_ohlc`: 63 gap days, 3764 missing ticker-date pairs.
  - Early YTD coverage is mostly SPY-only, then partial until 2026-04-02.
  - This is Massive-backed, not UW-backed.
- `stock_analytics_daily`: 2 missing pairs, both around 2026-01-26..2026-01-27.
- `vrp_daily`: 2 missing pairs, same 2026-01-26..2026-01-27 hole.
- `realized_volatility_history`: 2 missing pairs, same 2026-01-26..2026-01-27 hole.
- `volatility_stats_history`: 117 gap days, 9397 missing pairs.
  - Current table starts at 2026-05-11 and remains sparse for KORU/SOXL-like late additions.
- `greek_exposure_daily`: strict gap is 2026-06-29, only 2/103 covered.
  - Existing `data_freshness_snapshots` reports 100% because it uses a grace window around max date. The healer must record exact session coverage separately.
- `flow_alerts_daily_rollup`: 122 gap days, 8776 missing pairs.
  - This table is fundamentally sparse before flow ingestion existed; only heal from existing raw `flow_events` or explicit UW historical availability.

Snapshot/intraday findings:

- `intraday_quote`: 103/103 active rows, 100/103 fresh within 2 minutes.
  - Stale: XOM and XLF from `massive.com_ws` at 2026-06-29 23:53 HKT, XLE from `xenon_ws` around 8.5 minutes stale at scan time.
- `watchlist_card`: 103/103 active cards updated within 12 hours.
- `market_tide_snapshots`: 2026-06-29 has 81 bars but all captured in one post-close batch at 2026-06-30 10:46 HKT and `spot_rows=0`.
- `top_net_impact_snapshots`: only 2026-06-29, 40 rows captured once at 2026-06-30 10:49 HKT.
- `pipeline_benchmark_snapshots`: 0 rows. The scheduled job is failing every 5 minutes because `scheduler_heartbeat_lag_seconds` can be negative, violating the nonnegative check constraint.
- `ws_consumer_state`: active source `xenon_ws`, last flush age 0s, no error.

### Current Running Backfill

Macmini process:

- PID: `75761`
- Command: `/opt/homebrew/bin/uv run python -u /tmp/argon_option_surface_targeted_20260630.py`
- Log: `/Users/moremeds/projects/argon/logs/option-surface-targeted-20260630.err.log`
- Status at 2026-06-30 11:43 HKT: alive, working through 2026-06-10, UW daily count around 2718/60000, sleeping on minute throttle.

Do not start a second UW-heavy option-surface run until this process finishes or is intentionally stopped.

## Design Principles

- The healer is exact; the existing freshness monitor is coarse.
- Dry-run is default. Execution requires `--execute --confirm`.
- Every external-call adapter has a request budget and a resumable state row.
- A gap item is not "done" until the post-write verifier observes coverage in the target table.
- Known no-data cases are first-class records, not comments in logs.
- Existing production writers are reused:
  - Option surface: `option_surface_capture._build_ticker_rows` + `repo.upsert_option_surface_grid`
  - Greek exposure daily: `greek_exposure_daily_refresh`
  - OHLC: `ohlc_pull_once` / `MassiveOhlcProvider`
  - VRP/analytics: `nightly_vol_analytics_rollup`
  - Market tide/top-net: `scanners.market_tide.run`, `scanners.top_net_impact.run`
  - Market tide sentiment: `refresh_eod_sentiment`
- No new broad `repository.py` methods. New persistence gets its own storage module.
- Scheduler integration is opt-in and low-budget only until manual CLI runs prove safe.

## Dataset Classification

The healer must cover **all recorded datasets** through one of three outcomes:

1. Strict coverage audit + optional heal.
2. Freshness/state audit only, when exact ticker-date coverage is not meaningful.
3. Explicit exclusion with a stored reason, when the table is audit/provenance/research/operator state and should not be "backfilled".

### Tier 1: Safe DB-to-DB Heals

These can run without UW/Massive budget:

- `market_tide_sentiment_daily` from `market_tide_snapshots`
- `vrp_daily`, `stock_analytics_daily`, and `realized_volatility_history` from stored vol/OHLC via `nightly_vol_analytics_rollup`
- `flow_alerts_daily_rollup` only from existing raw `flow_events`

### Tier 2: Non-UW Provider Heals

These spend Massive budget, not UW:

- `daily_ohlc` via `MassiveOhlcProvider.fetch_daily`

### Tier 3: UW-Budgeted Heals

These must be capped and resumable:

- `option_surface_grid_daily`
- `greek_exposure_daily`
- `market_tide_snapshots`
- `top_net_impact_snapshots`
- `option_intraday_buckets`

### Tier 4: Forward-Only / Retention-Limited

These should be marked with caveats if historical data is unavailable:

- `top_net_impact_snapshots`: historical depends on UW date-param support and retention.
- `option_intraday_buckets`: retention-limited; old contracts return empty.
- `flow_alerts_daily_rollup`: pre-ingest gaps may be unhealable unless raw flow exists.
- `option_surface_grid_daily`: UW per-strike history is finite; after retention expires, gaps become permanent no-data.

## Recorded Dataset Registry

Task 1 must encode this registry in code. Do not rely on a static hand query only: the CLI should also have `audit --discover` that lists any date/time table missing from the registry and fails CI if the registry is stale.

### Provider Raw / Provenance / Audit

Audit/freshness only, not healed directly:

- `raw_payloads`
- `api_request_audit`
- `external_api_requests`
- `scan_runs`
- `jobs`
- `worker_heartbeat`
- `pipeline_benchmark_snapshots`
- `data_freshness_snapshots`
- `volatility_backfill_status`
- `ws_consumer_state`

### Watchlist, Scanner, and Stock Page State

Strict or freshness coverage depending on table shape:

- `watchlist`
- `watchlist_card`
- `scan_universe`
- `scan_results`
- `opportunity_scores`
- `structure_ideas`
- `signal_hits`
- `signal_context_flags`
- `signal_gates`
- `scanner_candidate_snapshots`
- `trade_insight_snapshots`
- `trade_insight_candidates`
- `trade_insight_ai_analyses`
- `trade_insight_outcomes`

### Core Per-Ticker Market Data

Strict ticker/date audit and heal where source retention allows:

- `daily_ohlc`
- `intraday_quote`
- `pcr_history`
- `options_volume_daily`
- `flow_alerts_daily_rollup`
- `flow_events`
- `dark_pool_events`
- `option_contract_snapshots`
- `option_intraday_buckets`
- `option_chain_per_strike`
- `option_surface_snapshots`
- `option_surface_grid_daily`
- `iv_rank_history`
- `iv_term_snapshots`
- `interpolated_iv_snapshots`
- `risk_reversal_skew_history`
- `greeks_by_expiry_strike`
- `exposures_by_expiry_strike`
- `exposures_summary`
- `oi_by_strike`
- `oi_by_expiry`
- `oi_change_events`
- `max_pain_by_expiry`
- `greek_exposure_daily`
- `short_interest_snapshots`
- `uw_positioning`
- `massive_fundamentals`
- `corporate_actions`

### Volatility, VRP, Skew, and Dealer-Derived Tables

Mostly DB-to-DB or derived from already-recorded chain/OHLC data:

- `index_ohlc_daily`
- `vol_index_daily`
- `realized_volatility_history`
- `volatility_stats_history`
- `iv_smile_snapshots`
- `stock_analytics_daily`
- `vrp_daily`
- `vrp_30d_settlements`
- `vrp_rv_validation`
- `vrp_harvest_verdicts`
- `vrp_harvest_by_sector`
- `vrp_harvest_multihorizon`
- `vrp_directional_verdicts`
- `vrp_dvrp_reversion`
- `vrp_trade_candidates`
- `vrp_backtest_results`
- `vrp_backtest_trades`
- `vrp_paper_positions`
- `vrp_leg_nbbo`
- `vrp_macro_sweep_results`
- `vrp_macro_signal_daily`
- `vrp_macro_entry`
- `vrp_macro_entry_quote`
- `vrp_macro_entry_grid`
- `skew_analytics_snapshot`
- `skew_swing_greeks`
- `skew_directional_verdicts`
- `skew_rv_reversion_verdicts`
- `vanna_signals`
- `charm_signals`
- `iv_source_validation`

### Regime / Market-Wide Tables

Session-level audit; heal only if the source or DB input supports the historical date:

- `market_tide_snapshots`
- `market_tide_sentiment_daily`
- `top_net_impact_snapshots`
- `gex_snapshots`
- `cri_snapshots`
- `vcg_snapshots`
- `grg_snapshots`
- `matrix_state_snapshots`
- `canary_snapshots`
- `regime_backtest_runs`
- `regime_backtest_daily`

### Rates, Gold, Macro, and Credit Lake Tables

These are recorded data too, but use non-watchlist calendars and source-specific expected frequencies:

- `macro_series_daily`
- `macro_series_monthly`
- `rates_observations`
- `rates_snapshots`
- `rates_policy_events`
- `rates_policy_path`
- `rates_cftc_tff_weekly`
- `rates_treasury_auctions`
- `rates_fiscal_debt_daily`
- `gold_posture_daily`
- `etf_holdings_daily`
- `etf_flows_daily`
- `etf_aum_cache`
- `wgc_etf_monthly`
- `wgc_etf_monthly_canonical`
- `uw_gold_options_daily`
- `exchange_inventory_daily`
- `cb_gold_reserves_monthly`
- `cot_gold_weekly`

### Registry Acceptance Rule

After implementation, this query must return zero unregistered tables:

```sql
SELECT table_name
FROM information_schema.columns
WHERE table_schema = 'uw_scan'
GROUP BY table_name
HAVING bool_or(
    data_type IN ('date','timestamp with time zone','timestamp without time zone')
    OR lower(column_name) LIKE '%date%'
    OR lower(column_name) LIKE '%time%'
    OR lower(column_name) LIKE '%_at'
)
EXCEPT
SELECT table_name FROM data_gap_dataset_registry;
```

## Target Schema

Create next migration after current head. At time of scan, current migration head is `091_market_tide_sentiment_daily.sql`; use `092_data_gap_healer.sql` unless another migration lands first.

### Tables

`data_gap_runs`

- `id BIGSERIAL PRIMARY KEY`
- `started_at TIMESTAMPTZ NOT NULL DEFAULT now()`
- `finished_at TIMESTAMPTZ`
- `mode TEXT NOT NULL CHECK (mode IN ('audit','plan','execute'))`
- `status TEXT NOT NULL CHECK (status IN ('running','complete','failed','cancelled'))`
- `start_date DATE`
- `end_date DATE`
- `datasets TEXT[] NOT NULL DEFAULT '{}'`
- `uw_budget_cap INTEGER`
- `massive_budget_cap INTEGER`
- `summary_jsonb JSONB NOT NULL DEFAULT '{}'::jsonb`
- `created_by TEXT NOT NULL DEFAULT current_user`

`data_gap_items`

- `id BIGSERIAL PRIMARY KEY`
- `run_id BIGINT NOT NULL REFERENCES data_gap_runs(id) ON DELETE CASCADE`
- `dataset TEXT NOT NULL`
- `data_date DATE`
- `ticker TEXT`
- `scope_key TEXT NOT NULL`
- `expected_count INTEGER`
- `covered_count INTEGER`
- `estimated_requests INTEGER NOT NULL DEFAULT 0`
- `actual_requests INTEGER NOT NULL DEFAULT 0`
- `status TEXT NOT NULL CHECK (status IN ('planned','running','healed','no_data','skipped_budget','failed'))`
- `reason TEXT`
- `attempts INTEGER NOT NULL DEFAULT 0`
- `last_error TEXT`
- `verified_at TIMESTAMPTZ`
- `details_jsonb JSONB NOT NULL DEFAULT '{}'::jsonb`
- Unique: `(run_id, dataset, scope_key)`

`data_gap_caveats`

- `dataset TEXT NOT NULL`
- `ticker TEXT`
- `start_date DATE`
- `end_date DATE`
- `reason TEXT NOT NULL`
- `source TEXT NOT NULL`
- `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`
- Unique: `(dataset, ticker, start_date, end_date, reason)`
- Seed caveat: `('option_surface_grid_daily','SPCX',NULL,'2026-06-16','listed after 2026-06-17','manual')`

`data_gap_dataset_registry`

- `table_name TEXT PRIMARY KEY`
- `dataset_group TEXT NOT NULL`
- `audit_mode TEXT NOT NULL CHECK (audit_mode IN ('strict_ticker_date','strict_session','freshness_only','operational_state','provenance','research_artifact','excluded'))`
- `date_col TEXT`
- `ticker_col TEXT`
- `expected_frequency TEXT`
- `healer_adapter TEXT`
- `source_system TEXT`
- `retention_days INTEGER`
- `enabled BOOLEAN NOT NULL DEFAULT true`
- `reason TEXT`
- `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`

## Implementation Tasks

### Task 1: Add Exact Gap Model and Specs

**Files:**

- Create: `src/uw_scan/reports/data_gap_healer.py`
- Test: `tests/unit/reports/test_data_gap_healer_specs.py`

**Steps:**

1. Define dataclasses `DatasetSpec`, `GapItem`, `CoverageSummary`, `DatasetRegistryEntry`, and `EligibilityRule`.
2. Add specs for every table in the Recorded Dataset Registry section, not only the currently broken warm-store tables.
3. For each spec, assign one `audit_mode`:
   - `strict_ticker_date`: active watchlist/date denominator applies.
   - `strict_session`: session/date denominator applies but no ticker denominator.
   - `freshness_only`: latest data/write age is meaningful, exact coverage is not.
   - `operational_state`: liveness/state table; no historical gap healing.
   - `provenance`: audit/raw/event log; no rewriting/backfilling.
   - `research_artifact`: persisted backtest/research output; audit for existence only.
   - `excluded`: intentionally outside healer scope with a required reason.
4. Implement `eligible_tickers_for_date(active_tickers, data_date, caveats)`.
5. Add the `SPCX` pre-2026-06-17 exclusion as data, not hardcoded SQL.
6. Add `discover_unregistered_tables(conn, schema)` and fail if any date/time table lacks a registry row.
7. Add tests for:
   - `SPCX` excluded on 2026-06-16 and included on 2026-06-17.
   - Strict session coverage differs from grace-window freshness.
   - Tickerless snapshot specs produce session-level items.
   - Every registered dataset has an `audit_mode`.
   - Discovery returns an unregistered synthetic table in tests.

Run:

```bash
uv run pytest tests/unit/reports/test_data_gap_healer_specs.py -q
```

Commit:

```bash
git add src/uw_scan/reports/data_gap_healer.py tests/unit/reports/test_data_gap_healer_specs.py
git commit -m "feat(data): model exact gap healer specs"
```

### Task 2: Add Persistence for Runs, Items, and Caveats

**Files:**

- Create: `src/uw_scan/storage/migrations/092_data_gap_healer.sql`
- Create: `src/uw_scan/storage/data_gap_healer_repository.py`
- Test: `tests/integration/storage/test_data_gap_healer_repository.py`

**Steps:**

1. Write idempotent migration with `CREATE TABLE IF NOT EXISTS`.
2. Add indexes:
   - `data_gap_runs(status, started_at DESC)`
   - `data_gap_items(dataset, data_date, ticker, status)`
   - `data_gap_caveats(dataset, ticker, start_date, end_date)`
   - `data_gap_dataset_registry(dataset_group, audit_mode)`
3. Implement repository methods:
   - `create_run`
   - `finish_run`
   - `upsert_items`
   - `claim_next_items`
   - `mark_item_healed`
   - `mark_item_no_data`
   - `mark_item_failed`
   - `list_caveats`
   - `list_dataset_registry`
   - `upsert_dataset_registry`
   - `list_unregistered_time_tables`
4. Seed the `SPCX` caveat in the migration with `ON CONFLICT DO NOTHING`.
5. Seed all entries from the Recorded Dataset Registry into `data_gap_dataset_registry` with `ON CONFLICT DO UPDATE`.
6. Write integration tests against the local test DB.
7. Add an assertion that `list_unregistered_time_tables()` returns zero for the migrated test schema after seeding.

Run:

```bash
UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/storage/test_data_gap_healer_repository.py -q
```

Commit:

```bash
git add src/uw_scan/storage/migrations/092_data_gap_healer.sql src/uw_scan/storage/data_gap_healer_repository.py tests/integration/storage/test_data_gap_healer_repository.py
git commit -m "feat(data): persist gap healer runs and items"
```

### Task 3: Implement Read-Only Coverage Scanner

**Files:**

- Modify: `src/uw_scan/reports/data_gap_healer.py`
- Create: `scripts/backfill/data_gap_healer.py`
- Test: `tests/integration/reports/test_data_gap_healer_scan.py`

**Steps:**

1. Add schema-driven date/ticker column detection, matching the live scan:
   - Date preference: `market_date`, `trade_date`, `session_date`, `data_date`, `curr_date`, `as_of_date`, `date`.
   - Ticker preference: `ticker`, `symbol`, `underlying`, `underlying_symbol`.
2. Use `market_tide_sentiment_daily.data_date` as the default equity-session calendar for watchlist-scoped tables.
3. For registry rows with `expected_frequency` outside the equity-session calendar, use the registry-specific frequency:
   - monthly for WGC/monthly macro/gold reserve tables.
   - weekly for CFTC tables.
   - event-driven for corporate actions, policy events, trade insights, and research artifacts.
   - liveness window for operational state tables.
4. Produce gap or freshness items according to `audit_mode`.
5. Add `audit --discover`; it must fail nonzero if any date/time table is absent from `data_gap_dataset_registry`.
6. Add CLI command:

```bash
uv run python scripts/backfill/data_gap_healer.py audit \
  --start 2026-01-01 \
  --end 2026-06-29 \
  --datasets option_surface_grid_daily,daily_ohlc,greek_exposure_daily
```

7. The audit command must write a `data_gap_runs` row and planned `data_gap_items`, but must not call UW/Massive.
8. Print a compact summary grouped by dataset and audit mode.

Run:

```bash
UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/reports/test_data_gap_healer_scan.py -q
```

Macmini dry evidence:

```bash
UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard uv run python scripts/backfill/data_gap_healer.py audit --start 2026-01-01 --end 2026-06-29
```

Commit:

```bash
git add src/uw_scan/reports/data_gap_healer.py scripts/backfill/data_gap_healer.py tests/integration/reports/test_data_gap_healer_scan.py
git commit -m "feat(data): audit exact warm-store gaps"
```

### Task 4: Add Budget Manager

**Files:**

- Create: `src/uw_scan/worker/jobs/data_gap_budget.py`
- Test: `tests/unit/worker/test_data_gap_budget.py`

**Steps:**

1. Implement `RequestBudget` with:
   - `provider`
   - `absolute_cap`
   - `run_cap`
   - `min_remaining`
   - `current_count`
   - `daily_limit`
2. Implement `can_spend(n)` and `record_spend(n)`.
3. For UW, read current count from `UwClient.rate_limit` after a probe only when execution begins.
4. For dry-run, use estimated counts only and make zero provider calls.
5. Stop by marking remaining planned items `skipped_budget`, not by crashing.

Run:

```bash
uv run pytest tests/unit/worker/test_data_gap_budget.py -q
```

Commit:

```bash
git add src/uw_scan/worker/jobs/data_gap_budget.py tests/unit/worker/test_data_gap_budget.py
git commit -m "feat(data): add provider budget guard for gap healing"
```

### Task 5: Option Surface Adapter

**Files:**

- Create: `src/uw_scan/worker/jobs/data_gap_adapters.py`
- Modify: `scripts/backfill/data_gap_healer.py`
- Test: `tests/integration/worker/test_data_gap_option_surface_adapter.py`

**Steps:**

1. Add `OptionSurfaceAdapter`.
2. Reuse `option_surface_capture._build_ticker_rows` and `repo.upsert_option_surface_grid`.
3. Estimate requests as `1 + expiry_count` per ticker-date when known; otherwise default to 20.
4. Execution must:
   - Insert a scan run with notes `data_gap_healer:option_surface`.
   - Commit per ticker-date.
   - Verify `option_surface_grid_daily` has rows for `(ticker, market_date)`.
   - Mark zero-row eligible responses as `no_data` only when provider call succeeded and verifier still sees no rows.
5. Add `--max-uw-calls` to CLI execute path.
6. Add tests with mocked UW fetchers; no live UW in default tests.

Run:

```bash
UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/worker/test_data_gap_option_surface_adapter.py -q
```

Small macmini dry-run:

```bash
UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard uv run python scripts/backfill/data_gap_healer.py plan --datasets option_surface_grid_daily --start 2026-06-22 --end 2026-06-22 --max-uw-calls 100
```

Commit:

```bash
git add src/uw_scan/worker/jobs/data_gap_adapters.py scripts/backfill/data_gap_healer.py tests/integration/worker/test_data_gap_option_surface_adapter.py
git commit -m "feat(data): heal option surface gaps with budgeted adapter"
```

### Task 6: DB-to-DB and Massive Adapters

**Files:**

- Modify: `src/uw_scan/worker/jobs/data_gap_adapters.py`
- Test: `tests/integration/worker/test_data_gap_db_adapters.py`

**Steps:**

1. Add `MarketTideSentimentAdapter` that calls `refresh_eod_sentiment`.
2. Add `VolAnalyticsAdapter` that calls `nightly_vol_analytics_rollup`.
3. Add `FlowRollupAdapter` that only derives from existing `flow_events`; if no raw rows exist, mark `no_data` with reason `raw_flow_missing`.
4. Add `DailyOhlcAdapter` using `MassiveOhlcProvider.fetch_daily`.
5. Verify after each adapter by querying target coverage.
6. Keep Massive and UW budgets separate.

Run:

```bash
UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/worker/test_data_gap_db_adapters.py -q
```

Commit:

```bash
git add src/uw_scan/worker/jobs/data_gap_adapters.py tests/integration/worker/test_data_gap_db_adapters.py
git commit -m "feat(data): heal db and OHLC coverage gaps"
```

### Task 7: Market Tide, Top Net Impact, and Greek Exposure Adapters

**Files:**

- Modify: `src/uw_scan/worker/jobs/data_gap_adapters.py`
- Test: `tests/integration/worker/test_data_gap_market_adapters.py`

**Steps:**

1. Add `MarketTideAdapter` using `scanners.market_tide.run(capture_spot=False)`.
2. Add `TopNetImpactAdapter` using `scanners.top_net_impact.run`.
3. Add `GreekExposureDailyAdapter` using `greek_exposure_daily_refresh` with a ticker filter.
4. Add retention behavior:
   - Empty successful market-tide day: `no_data` with `holiday_or_unavailable`.
   - Empty top-net historical response: `no_data` with `provider_history_unavailable`.
   - Greek exposure missing after a successful aggregate call: `no_data` with `provider_no_history`.
5. Include strict verifier so the June 29 `greek_exposure_daily` gap cannot be hidden by the freshness monitor grace window.

Run:

```bash
UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/worker/test_data_gap_market_adapters.py -q
```

Commit:

```bash
git add src/uw_scan/worker/jobs/data_gap_adapters.py tests/integration/worker/test_data_gap_market_adapters.py
git commit -m "feat(data): heal market snapshot and greek exposure gaps"
```

### Task 8: CLI Execute and Resume Semantics

**Files:**

- Modify: `scripts/backfill/data_gap_healer.py`
- Test: `tests/integration/scripts/test_data_gap_healer_cli.py`

**Steps:**

1. CLI subcommands:
   - `audit`
   - `plan`
   - `execute`
   - `resume`
   - `verify`
2. `audit`: creates a run and planned items, zero provider calls.
3. `plan`: same as audit, with request estimates and provider budget projection.
4. `execute`: requires `--confirm`, claims planned items, executes adapters, verifies each item.
5. `resume --run-id N`: continues planned/failed/skipped_budget items.
6. `verify --run-id N`: recomputes strict coverage and prints before/after.
7. Make output machine-readable with `--json` and human-readable by default.

Run:

```bash
UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/scripts/test_data_gap_healer_cli.py -q
```

Commit:

```bash
git add scripts/backfill/data_gap_healer.py tests/integration/scripts/test_data_gap_healer_cli.py
git commit -m "feat(data): add resumable gap healer cli"
```

### Task 9: Scheduler Integration Behind a Kill Switch

**Files:**

- Modify: `src/uw_scan/config.py`
- Create: `src/uw_scan/worker/jobs/data_gap_healer.py`
- Modify: `src/uw_scan/worker/scheduler.py`
- Test: `tests/integration/worker/test_data_gap_healer_scheduler.py`

**Steps:**

1. Add settings (eng-review: nightly capped backfill per intention #3; full coverage incl. macro/FRED):
   - `DATA_GAP_HEALER_ENABLED=false`            # flip true to enable the nightly backfill
   - `DATA_GAP_HEALER_CRON_ET="0 20 * * 1-5"`   # 20:00 America/New_York, weekdays (after UW reset)
   - `DATA_GAP_HEALER_DATASETS=""`              # empty = ALL healable datasets (full coverage); CSV to narrow
   - `DATA_GAP_HEALER_START="2026-01-01"`       # audit/heal from here to today — as much history as possible
   - `DATA_GAP_HEALER_MAX_UW_CALLS=20000`       # configurable UW request cap (the ONLY cap; massive/external uncapped)
2. Register the job at `DATA_GAP_HEALER_CRON_ET` only when `DATA_GAP_HEALER_ENABLED`.
3. Scheduled mode runs `audit` then `execute` over `DATA_GAP_HEALER_DATASETS` including UW heals, bounded by the caps above; over-cap → `skipped_budget`.
4. Advisory lock + guard: skip if a manual UW backfill or a prior healer run is still `running`.
5. Log run id + summary, write the report artifact, refresh `/api/health`.

Run:

```bash
UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/worker/test_data_gap_healer_scheduler.py -q
```

Commit:

```bash
git add src/uw_scan/config.py src/uw_scan/worker/jobs/data_gap_healer.py src/uw_scan/worker/scheduler.py tests/integration/worker/test_data_gap_healer_scheduler.py
git commit -m "feat(data): schedule opt-in low-risk gap healing"
```

### Task 10: Fix Benchmark Snapshot Persistence

**Files:** (eng-review: NO migration — the `>= 0` CHECK in `058` is correct; fix the producer)

- Modify: `src/uw_scan/benchmark/collector.py`
- Test: `tests/integration/worker/test_pipeline_benchmark_snapshot_job.py`

**Steps:**

1. Root cause: `scheduler_heartbeat_lag_seconds` can be negative because the latest heartbeat can race slightly after the benchmark `now_utc`. The constraint is right; the producer is wrong.
2. Clamp lags to `max(0, computed_seconds)` in the collector (`collector.py:95`).
3. ~~Add migration that drops/recreates the check~~ — **removed**. Keep the existing `058` CHECK `(scheduler_heartbeat_lag_seconds >= 0)`; do not relax a correct invariant.
4. Add regression test inserting a synthetic future heartbeat and proving snapshot persistence succeeds (lag clamps to 0, no constraint violation).
5. Verify macmini after deploy: `pipeline_benchmark_snapshots.last24 > 0`.

Run:

```bash
UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/worker/test_pipeline_benchmark_snapshot_job.py -q
```

Commit:

```bash
git add src/uw_scan/benchmark/collector.py tests/integration/worker/test_pipeline_benchmark_snapshot_job.py
git commit -m "fix(health): persist benchmark snapshots when heartbeat races"
```

### Task 11: Health/API Surfacing

**Files:**

- Modify: `src/uw_scan/api/routers/health.py`
- Test: `tests/integration/api/test_health_gap_healer.py`

**Steps:**

1. Add a `gap_healer` health block:
   - latest run id/status
   - open gap items by dataset
   - failed/no_data counts
   - last successful verify timestamp
2. Keep `data_freshness` separate; it answers "fresh enough", not "all strict gaps healed".
3. Add OpenAPI snapshot update.

Run:

```bash
UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/api/test_health_gap_healer.py tests/integration/api/test_openapi_snapshot.py -q
```

Commit:

```bash
git add src/uw_scan/api/routers/health.py tests/integration/api/test_health_gap_healer.py tests/integration/api/openapi.snapshot.json
git commit -m "feat(health): expose gap healer status"
```

### Task 12: Runbook and Operator Commands

**Files:**

- Modify: `docs/runbooks/release.md`
- Create: `docs/runbooks/data-gap-healer.md`
- Modify: `CHANGELOG.md`

**Steps:**

1. Document safe command patterns:

```bash
# Audit only, no provider calls
UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard \
  uv run python scripts/backfill/data_gap_healer.py audit --start 2026-01-01 --end 2026-06-29

# Execute only DB-to-DB repairs
UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard \
  uv run python scripts/backfill/data_gap_healer.py execute --datasets market_tide_sentiment_daily,vrp_daily --confirm

# Execute UW-budgeted option surface with a hard run cap
UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard \
  uv run python scripts/backfill/data_gap_healer.py execute --datasets option_surface_grid_daily --max-uw-calls 25000 --confirm
```

2. Document caveat lifecycle:
   - add caveat
   - rerun audit
   - verify missing pairs drop without provider calls
3. Document what not to automate:
   - full option surface history while live stack needs budget
   - option intraday beyond provider retention
   - top net impact if UW historical endpoint returns only current session

Run:

```bash
uv run python -m compileall scripts/backfill/data_gap_healer.py src/uw_scan/reports/data_gap_healer.py src/uw_scan/worker/jobs/data_gap_healer.py
```

Commit:

```bash
git add docs/runbooks/data-gap-healer.md docs/runbooks/release.md CHANGELOG.md
git commit -m "docs(data): document gap healer operations"
```

### Task 13: Full Dataset Policy Matrix

**Files:**

- Create: `docs/runbooks/data-gap-dataset-policy.md`
- Modify: `src/uw_scan/reports/data_gap_healer.py`
- Test: `tests/unit/reports/test_data_gap_dataset_policy.py`

**Steps:**

1. Add a `DatasetPolicy` object for every `data_gap_dataset_registry` row.
2. Encode for each dataset:
   - `audit_mode`
   - expected calendar/frequency
   - owner/source
   - whether historical repair is allowed
   - adapter name, if any
   - reason if no adapter is allowed
   - verifier query shape
3. Split policy groups into:
   - `core_watchlist`
   - `options_chain`
   - `scanner_state`
   - `derived_volatility`
   - `regime_marketwide`
   - `gold_rates_macro`
   - `research_artifact`
   - `operational_provenance`
4. Generate a Markdown table from the registry and commit it to `docs/runbooks/data-gap-dataset-policy.md`.
5. Add tests proving every registry row has a policy and every healable policy has an adapter or an explicit implementation TODO blocked by source-retention evidence.

Run:

```bash
uv run pytest tests/unit/reports/test_data_gap_dataset_policy.py -q
```

Commit:

```bash
git add src/uw_scan/reports/data_gap_healer.py docs/runbooks/data-gap-dataset-policy.md tests/unit/reports/test_data_gap_dataset_policy.py
git commit -m "feat(data): define policy for every recorded dataset"
```

### Task 14: Core Watchlist and Options-Chain Adapter Pack

**Files:**

- Modify: `src/uw_scan/worker/jobs/data_gap_adapters.py`
- Test: `tests/integration/worker/test_data_gap_core_options_adapters.py`

**Steps:**

1. Add strict verifier functions for:
   - `options_volume_daily`
   - `flow_events`
   - `dark_pool_events`
   - `option_contract_snapshots`
   - `option_chain_per_strike`
   - `iv_rank_history`
   - `iv_term_snapshots`
   - `interpolated_iv_snapshots`
   - `risk_reversal_skew_history`
   - `greeks_by_expiry_strike`
   - `exposures_by_expiry_strike`
   - `exposures_summary`
   - `oi_by_strike`
   - `oi_by_expiry`
   - `oi_change_events`
   - `max_pain_by_expiry`
   - `short_interest_snapshots`
   - `uw_positioning`
   - `pcr_history`
2. Classify each as one of:
   - directly healable by existing full scan / flow refresh / cockpit daily snapshot.
   - derived from another table and healed by re-running the derived job.
   - freshness-only because the table is event/log shaped.
   - no-data when source retention prevents historical repair.
3. Add adapters only where the production writer path already exists:
   - `flow_data_refresh`
   - `full_scan`
   - `cockpit_daily_snapshot`
   - `positioning_refresh_once`
4. Do not create ad hoc row writers for raw/event tables.
5. Add integration tests with faked clients proving adapter dispatch uses the production job path.

Run:

```bash
UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/worker/test_data_gap_core_options_adapters.py -q
```

Commit:

```bash
git add src/uw_scan/worker/jobs/data_gap_adapters.py tests/integration/worker/test_data_gap_core_options_adapters.py
git commit -m "feat(data): cover core options datasets in gap healer"
```

### Task 15: Derived Volatility, VRP, and Skew Adapter Pack

**Files:**

- Modify: `src/uw_scan/worker/jobs/data_gap_adapters.py`
- Test: `tests/integration/worker/test_data_gap_derived_vol_adapters.py`

**Steps:**

1. Add policy/verifier coverage for:
   - `index_ohlc_daily`
   - `vol_index_daily`
   - `realized_volatility_history`
   - `volatility_stats_history`
   - `iv_smile_snapshots`
   - `stock_analytics_daily`
   - `vrp_daily`
   - `vrp_30d_settlements`
   - `vrp_rv_validation`
   - `iv_source_validation`
   - `skew_analytics_snapshot`
   - `skew_swing_greeks`
   - `skew_directional_verdicts`
   - `skew_rv_reversion_verdicts`
   - `vanna_signals`
   - `charm_signals`
2. Reuse existing derivation jobs where possible:
   - `nightly_vol_analytics_rollup`
   - `run_volatility_backfill`
   - `skew_analytics_backfill`
   - `skew_swing_greeks_refresh`
   - VRP markout/research jobs for persisted result tables.
3. Mark backtest and paper-trade result tables as `research_artifact` unless the command includes `--include-research-artifacts`.
4. Add tests proving research artifacts are audited but not mutated by default.

Run:

```bash
UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/worker/test_data_gap_derived_vol_adapters.py -q
```

Commit:

```bash
git add src/uw_scan/worker/jobs/data_gap_adapters.py tests/integration/worker/test_data_gap_derived_vol_adapters.py
git commit -m "feat(data): cover volatility vrp and skew datasets"
```

### Task 16: Regime, Market-Wide, Gold, Rates, and Macro Adapter Pack

**Files:**

- Modify: `src/uw_scan/worker/jobs/data_gap_adapters.py`
- Test: `tests/integration/worker/test_data_gap_macro_regime_adapters.py`

**Steps:**

1. Add session-level policies and verifiers for:
   - `gex_snapshots`
   - `cri_snapshots`
   - `vcg_snapshots`
   - `grg_snapshots`
   - `matrix_state_snapshots`
   - `canary_snapshots`
   - `vrp_macro_signal_daily`
   - `vrp_macro_entry`
   - `vrp_macro_entry_quote`
   - `vrp_macro_entry_grid`
2. Add source-frequency policies and verifiers for:
   - `macro_series_daily`
   - `macro_series_monthly`
   - `rates_observations`
   - `rates_snapshots`
   - `rates_policy_events`
   - `rates_policy_path`
   - `rates_cftc_tff_weekly`
   - `rates_treasury_auctions`
   - `rates_fiscal_debt_daily`
   - `gold_posture_daily`
   - `etf_holdings_daily`
   - `etf_flows_daily`
   - `etf_aum_cache`
   - `wgc_etf_monthly`
   - `wgc_etf_monthly_canonical`
   - `uw_gold_options_daily`
   - `exchange_inventory_daily`
   - `cb_gold_reserves_monthly`
   - `cot_gold_weekly`
3. Reuse existing jobs where available:
   - regime scanners and `regime_jobs --backfill`.
   - market tide/top-net adapters from Task 7.
   - gold jobs in `src/uw_scan/worker/jobs/gold_jobs.py`.
   - rates jobs in `src/uw_scan/worker/jobs/rates_jobs.py`.
4. For source families without historical API support, emit `no_data`/`freshness_only` with a policy reason rather than retrying forever.
5. Add tests for weekly, monthly, and event-driven expected-frequency handling.

Run:

```bash
UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/worker/test_data_gap_macro_regime_adapters.py -q
```

Commit:

```bash
git add src/uw_scan/worker/jobs/data_gap_adapters.py tests/integration/worker/test_data_gap_macro_regime_adapters.py
git commit -m "feat(data): cover regime gold rates and macro datasets"
```

### Task 17: Full Verification and Evidence Export

**Files:**

- Modify: `scripts/backfill/data_gap_healer.py`
- Create: `src/uw_scan/reports/data_gap_evidence.py`
- Test: `tests/integration/scripts/test_data_gap_healer_full_verify.py`

**Steps:**

1. Add CLI command:

```bash
uv run python scripts/backfill/data_gap_healer.py verify-all --start 2026-01-01 --end 2026-06-29 --json
```

2. `verify-all` must:
   - run discovery.
   - assert zero unregistered date/time tables.
   - run all enabled policies.
   - emit strict/freshness/research/provenance summaries separately.
   - write an evidence artifact under `output/playwright/` or `output/data-gap/` if that directory already exists; otherwise create `output/data-gap/`.
3. Evidence artifact must include:
   - command.
   - DB host/name/schema.
   - checked_at timestamp.
   - registry count.
   - missing item counts by dataset.
   - no-data caveat counts.
   - provider request delta for dry-run should be zero.
4. Add `--fail-on-open-gaps` for CI/operator use.
5. Add integration test verifying JSON shape and zero provider calls in dry-run.

Run:

```bash
UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/scripts/test_data_gap_healer_full_verify.py -q
```

Commit:

```bash
git add scripts/backfill/data_gap_healer.py src/uw_scan/reports/data_gap_evidence.py tests/integration/scripts/test_data_gap_healer_full_verify.py
git commit -m "feat(data): export full gap verification evidence"
```

### Task 18: Full-Service Scheduler and Safety Gates

**Files:**

- Modify: `src/uw_scan/config.py`
- Modify: `src/uw_scan/worker/jobs/data_gap_healer.py`
- Modify: `src/uw_scan/worker/scheduler.py`
- Test: `tests/integration/worker/test_data_gap_healer_full_service.py`

**Steps:**

1. Add settings:
   - `DATA_GAP_HEALER_MODE=audit`
   - `DATA_GAP_HEALER_FULL_REGISTRY_REQUIRED=true`
   - `DATA_GAP_HEALER_ALLOW_UW=false`
   - `DATA_GAP_HEALER_ALLOW_MASSIVE=true`
   - `DATA_GAP_HEALER_ALLOW_RESEARCH_ARTIFACTS=false`
   - `DATA_GAP_HEALER_MAX_ITEMS_PER_RUN=500`
2. Scheduled service defaults to `audit` and DB-to-DB/Massive-safe repairs only.
3. UW-backed repair remains manual unless `DATA_GAP_HEALER_ALLOW_UW=true`.
4. Add advisory lock and item claim limit so a scheduled run cannot fight a manual backfill.
5. Add guard that refuses UW-heavy execution if an active `option_surface_backfill` or `data_gap_healer` run is already `running`.
6. Add test proving scheduler refuses unsafe UW execution by default.

Run:

```bash
UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/worker/test_data_gap_healer_full_service.py -q
```

Commit:

```bash
git add src/uw_scan/config.py src/uw_scan/worker/jobs/data_gap_healer.py src/uw_scan/worker/scheduler.py tests/integration/worker/test_data_gap_healer_full_service.py
git commit -m "feat(data): run gap healer as a guarded full service"
```

### Task 19: Macmini Full Dry-Run and Limited Execute

**Files:**

- Create: `docs/runbooks/data-gap-healer-macmini-evidence.md`

**Steps:**

1. Wait for the currently running option-surface backfill PID `75761` to finish or intentionally stop it.
2. Run full discovery/audit:

```bash
UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard \
  uv run python scripts/backfill/data_gap_healer.py verify-all \
  --start 2026-01-01 --end 2026-06-29 --json
```

3. Confirm evidence says:
   - `unregistered_tables=0`.
   - dry-run provider request delta is zero.
   - every recorded table is in exactly one audit-mode bucket.
4. Run limited execute only for DB-to-DB datasets:

```bash
UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard \
  uv run python scripts/backfill/data_gap_healer.py execute \
  --datasets market_tide_sentiment_daily,vrp_daily,stock_analytics_daily,realized_volatility_history \
  --confirm
```

5. Re-run `verify-all` and record before/after counts.
6. Do not run full UW execution in this task; that stays a separate operator decision with an explicit call cap.

Run:

```bash
uv run python -m compileall scripts/backfill/data_gap_healer.py src/uw_scan/reports/data_gap_healer.py src/uw_scan/reports/data_gap_evidence.py src/uw_scan/worker/jobs/data_gap_healer.py
```

Commit:

```bash
git add docs/runbooks/data-gap-healer-macmini-evidence.md
git commit -m "docs(data): record macmini full gap-healer evidence"
```

## Final Verification Plan

Run before PR:

```bash
uv run pytest tests/unit/reports/test_data_gap_healer_specs.py tests/unit/reports/test_data_gap_dataset_policy.py tests/unit/worker/test_data_gap_budget.py -q
UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/storage/test_data_gap_healer_repository.py tests/integration/reports/test_data_gap_healer_scan.py -q
UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/worker/test_data_gap_option_surface_adapter.py tests/integration/worker/test_data_gap_db_adapters.py tests/integration/worker/test_data_gap_market_adapters.py tests/integration/worker/test_data_gap_core_options_adapters.py tests/integration/worker/test_data_gap_derived_vol_adapters.py tests/integration/worker/test_data_gap_macro_regime_adapters.py -q
UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/scripts/test_data_gap_healer_cli.py tests/integration/scripts/test_data_gap_healer_full_verify.py tests/integration/api/test_health_gap_healer.py -q
UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/worker/test_data_gap_healer_scheduler.py tests/integration/worker/test_data_gap_healer_full_service.py -q
cd web && npm run test
```

Run against macmini in dry mode:

```bash
UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard \
  uv run python scripts/backfill/data_gap_healer.py audit --start 2026-01-01 --end 2026-06-29 --json
```

Expected evidence:

- `data_gap_runs` has one completed audit run.
- `data_gap_items` has planned items matching current strict coverage query.
- `data_gap_dataset_registry` covers every date/time table in `uw_scan`.
- `verify-all` reports `unregistered_tables=0`.
- No UW/Massive request counts increased during audit.

Run one low-risk execute verification:

```bash
UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard \
  uv run python scripts/backfill/data_gap_healer.py execute --datasets market_tide_sentiment_daily --confirm
```

Expected evidence:

- Run completes.
- Items for the dataset are `healed` or `no_data`.
- Strict verifier reports no regression.

Do not run a UW-heavy execute while `/tmp/argon_option_surface_targeted_20260630.py` is still active.

## Merge Readiness Criteria

- All new tests pass locally.
- Macmini audit proves exact gap counts and writes no provider requests.
- One DB-to-DB execute proves run/item state, verification, and idempotency.
- Benchmark snapshot persistence has a regression test and no longer fails on negative heartbeat race.
- Full registry discovery proves `113/113` current macmini date/time tables are registered, or a fresh schema count with zero missing if the schema changes before merge.
- Full dry-run evidence exists for all audit modes: strict ticker/date, strict session, freshness-only, operational/provenance, and research artifact.
- PR description includes:
  - before/after strict coverage examples
  - registry coverage count
  - budget controls
  - known forward-only limitations
  - macmini dry-run evidence
