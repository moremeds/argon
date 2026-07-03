# UW Historical Alpha Backfill Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add durable, budget-aware YTD backfills for five UW-derived alpha datasets and wire them into Argon so the five shortlisted 1-3 week US-stock swing strategies can be researched and explored.

**Architecture:** Add small, append-only historical tables first, then fetchers/normalizers, then one resumable backfill CLI with a configurable UW request cap. Keep production exploration read-only: strategy assemblers read from the warm store and write research snapshots only after the raw/provider tables are verified.

**Tech Stack:** Python 3.13 via `uv`, psycopg 3, FastAPI/Pydantic v2, existing `UwClient`, existing raw-payload/audit tables, Postgres migrations under `src/uw_scan/storage/migrations/`, research docs under `docs/research/`.

---

## Current Facts And Request Math

Measured on 2026-07-02:

- Active watchlist tickers: `103`
- Clean YTD market-session spine: `124` sessions from `2026-01-02` through `2026-07-01`
- Weekday fallback count: `131`, but the plan should use the existing `market_tide_sentiment_daily` session spine because it excludes holidays.

Representative live probes:

- `/api/stock/AAPL/volatility/variance-risk-premium?date=2026-01-02` returned `250` rows ending `2026-01-02`.
- `/api/stock/AAPL/volatility/variance-risk-premium?date=2026-03-02` returned `251` rows ending `2026-03-02`.
- `/api/stock/AAPL/volatility/anomaly?date=2026-01-02` returned empty `history` and null `latest`.
- `/api/stock/AAPL/volatility/anomaly?date=2026-07-01` returned `16` history rows and latest `2026-07-01`.
- `/api/stock/AAPL/volatility/character?date=2026-07-01` returned `16` history rows and latest `2026-07-01`.
- `/api/stock/AAPL/gex-levels?date=2026-01-02` returned a valid object shape.

Implication:

- Full YTD is realistic for ticker VRP and GEX levels.
- Full YTD is likely **not** available from volatility anomaly/character today; persist the recent returned history and accumulate forward daily.
- Intraday flow and dark/lit date-selector endpoints should be backfilled promptly because UW's historical selectors are retention-limited.

## Estimated UW Requests For YTD

Baseline scope: 103 active watchlist tickers x 124 market sessions.

| Dataset | Endpoint pattern | Request formula | Estimated requests | Notes |
| --- | --- | ---: | ---: | --- |
| `uw_volatility_signal_daily` | anomaly + character + VRP | `103 * (1 + 1 + 1)` | `309` | One call each per ticker. Anomaly/character only save returned recent history; VRP saves all YTD rows from returned trailing series. |
| `uw_gex_levels_daily` | gex-levels by ticker/date | `103 * 124` | `12,772` | One compact request per ticker/session. |
| `uw_intraday_option_flow_bars` | net-prem-ticks + greek-flow by ticker/date | `103 * 124 * 2` | `25,544` | Baseline excludes per-expiry greek-flow to avoid expiry explosion. |
| `uw_dark_lit_flow_prints` | darkpool + lit-flow by ticker/date | `103 * 124 * 2` | `25,544` | Start with ticker/date and `limit=500`; later add cursor pagination for overflow days. |
| `uw_short_pressure_daily` | interest-float/v2 + ftds + volumes-by-exchange | `103 * 4` | `412` | Assumes one call each for interest-float and FTDs, plus up to two cursor pages for exchange short volume. |
| **Total baseline** |  |  | **64,581** | Add ~2-5% operational overhead for retries/no-data probes. |

Optional context requests:

- Market tide/top-net already exist in Argon and should not be duplicated here.
- Sector tide would add roughly `124 * 11 = 1,364` requests if added later.
- Per-expiry `greek-flow/{expiry}` should be a follow-up only for selected tickers/expiries, not part of the first YTD burn.

Recommended weekend cap:

- Default script cap: `20,000` UW calls, matching current `DATA_GAP_HEALER_MAX_UW_CALLS`.
- Long-weekend operator cap: `50,000-60,000` if live UW workers are paused or the run starts after quota reset.
- Use `--max-uw-calls` per invocation and stop gracefully at the cap.
- Read UW response headers (`x-uw-daily-req-count`, `x-uw-token-req-limit`) and stop before the provider hard cap even if the local cap is higher.

## New Tables

### `uw_volatility_signal_daily`

Key: `(ticker, market_date)`.

Columns:

- `ticker text not null`
- `market_date date not null`
- `anomaly_direction text`
- `anomaly_score numeric`
- `vol_character text`
- `half_life_days numeric`
- `hurst_rv numeric`
- `vrp_rank numeric`
- `risk_premium numeric`
- `source_mask text[] not null default '{}'`
- `raw_jsonb jsonb`
- `fetched_at timestamptz not null default now()`

### `uw_gex_levels_daily`

Key: `(ticker, market_date)`.

Columns:

- `ticker text not null`
- `market_date date not null`
- `call_wall numeric`
- `put_wall numeric`
- `gamma_flip numeric`
- `gamma_magnet numeric`
- `spot numeric`
- `raw_jsonb jsonb`
- `fetched_at timestamptz not null default now()`

### `uw_intraday_option_flow_bars`

Key: `(ticker, market_date, ts, source, expiry)`.

Columns:

- `ticker text not null`
- `market_date date not null`
- `ts timestamptz not null`
- `source text not null` (`net_prem_ticks` or `greek_flow`)
- `expiry date`
- `net_call_premium numeric`
- `net_put_premium numeric`
- `net_delta numeric`
- `call_volume bigint`
- `put_volume bigint`
- `dir_delta_flow numeric`
- `dir_vega_flow numeric`
- `otm_dir_delta_flow numeric`
- `otm_dir_vega_flow numeric`
- `transactions bigint`
- `volume bigint`
- `raw_jsonb jsonb`
- `fetched_at timestamptz not null default now()`

### `uw_dark_lit_flow_prints`

Key: `(source, tracking_id)`.

Columns:

- `source text not null` (`darkpool` or `lit_flow`)
- `tracking_id text not null`
- `ticker text not null`
- `executed_at timestamptz not null`
- `market_date date not null`
- `price numeric`
- `size bigint`
- `premium numeric`
- `market_center text`
- `nbbo_bid numeric`
- `nbbo_ask numeric`
- `nbbo_bid_quantity bigint`
- `nbbo_ask_quantity bigint`
- `sale_cond_codes text[]`
- `trade_code text`
- `raw_jsonb jsonb`
- `fetched_at timestamptz not null default now()`

### `uw_short_pressure_daily`

Key: `(ticker, market_date)`.

Columns:

- `ticker text not null`
- `market_date date not null`
- `short_interest numeric`
- `si_float numeric`
- `si_float_with_synth_long_pct_of_total_shares numeric`
- `days_to_cover numeric`
- `fee_rate numeric`
- `rebate_rate numeric`
- `short_shares_available numeric`
- `total_float numeric`
- `ftd_quantity numeric`
- `short_volume numeric`
- `total_volume numeric`
- `short_volume_ratio numeric`
- `raw_jsonb jsonb`
- `fetched_at timestamptz not null default now()`

## CLI Design

Create: `scripts/backfill/uw_historical_alpha_backfill.py`

Required behavior:

- `audit`: DB-only coverage report for the five datasets.
- `plan`: print request estimate for requested datasets/date range.
- `execute`: run backfill under a hard request cap.
- `resume`: continue the same run id after cap/restart.
- `verify`: recompute coverage and write evidence.

Suggested command:

```bash
UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard \
  uv run python scripts/backfill/uw_historical_alpha_backfill.py execute \
  --datasets uw_volatility_signal_daily,uw_gex_levels_daily,uw_intraday_option_flow_bars,uw_dark_lit_flow_prints,uw_short_pressure_daily \
  --start 2026-01-01 \
  --end 2026-07-01 \
  --max-uw-calls 50000 \
  --confirm
```

Config:

- Env: `UW_HISTORICAL_ALPHA_MAX_UW_CALLS`, default `20000`.
- CLI flag: `--max-uw-calls`, overrides env.
- Env: `UW_HISTORICAL_ALPHA_DATASETS`, optional CSV default.
- Env: `UW_HISTORICAL_ALPHA_START`, default `2026-01-01`.
- Env: `UW_HISTORICAL_ALPHA_END`, default latest session in the DB session spine.

Cap semantics:

- Count every UW HTTP response, including 403/422/no-data.
- Stop before local cap.
- Also stop if `x-uw-daily-req-count >= x-uw-token-req-limit - reserve`.
- Add `--uw-reserve-calls`, default `1000`, to leave room for live jobs unless explicitly set lower.
- Persist `skipped_budget` items so `resume` is deterministic.

Run metadata:

- Reuse `data_gap_runs` / `data_gap_items` if practical.
- If the existing gap healer registry is too coupled, create a narrower
  `uw_historical_alpha_backfill_runs` and `uw_historical_alpha_backfill_items`
  pair. Prefer reuse if it can represent the row keys cleanly.

## Argon Integration Path

1. Add endpoint slugs to `src/uw_scan/api/endpoints.py`:
   - `VOLATILITY_ANOMALY`
   - `VOLATILITY_CHARACTER`
   - `VARIANCE_RISK_PREMIUM`
   - `GEX_LEVELS`
   - `NET_PREM_TICKS`
   - `GREEK_FLOW`
   - `LIT_FLOW_TICKER`
   - `SHORT_FTDS`
   - `SHORT_VOLUMES_BY_EXCHANGE`
2. Add fetchers to `src/uw_scan/sources/uw.py`, preserving raw payload/audit before normalize.
3. Add Pydantic/domain row models under `src/uw_scan/models/`.
4. Add normalizers in `src/uw_scan/normalize.py`.
5. Add storage methods in a new `src/uw_scan/storage/uw_historical_alpha.py` mixin and assemble it in `repository.py`.
6. Add migration `095_uw_historical_alpha_tables.sql`.
7. Add backfill CLI.
8. Add the five datasets to the data-gap registry so coverage is visible in `/api/health`.
9. Add research assemblers:
   - `reports/uw_alpha_volatility.py`
   - `reports/uw_alpha_gex.py`
   - `reports/uw_alpha_flow.py`
   - `reports/uw_alpha_dark_lit.py`
   - `reports/uw_alpha_short_pressure.py`
10. Add a read-only API route under `/api/research/uw-alpha/*` only after data is persisted and verified.

## Strategy Enablement

### 1. Volatility Anomaly / VRP Reversion

Reads:

- `uw_volatility_signal_daily`
- existing `vrp_daily`
- existing `volatility_stats_history`
- existing `realized_volatility_history`

First signal:

- Rank high absolute anomaly score.
- Separate `long_vol`, `short_vol`, and `neutral`.
- Use `half_life_days` and `hurst_rv` to avoid fading persistent vol regimes.
- Backtest forward 5d/10d/15d stock returns first, then option spreads.

### 2. Dealer Gamma Wall Pin / Breakout

Reads:

- `uw_gex_levels_daily`
- `option_surface_grid_daily`
- spot/OHLC history

First signal:

- Pin/fade near `gamma_magnet` when call/put walls are tight.
- Breakout when close crosses `gamma_flip` and option flow confirms.
- Test 5d/10d/15d forward returns by distance-to-wall buckets.

### 3. Net Premium / Greek Flow Continuation

Reads:

- `uw_intraday_option_flow_bars`
- `top_net_impact_snapshots`
- `market_tide_sentiment_daily`

First signal:

- Aggregate first 60/120/RTH minutes of net premium and directional delta flow.
- Follow only persistent flow confirmed by price trend.
- Flag failed-flow reversals separately.

### 4. Dark/Lit Block Accumulation Confirmation

Reads:

- `uw_dark_lit_flow_prints`
- OHLCV history
- optional `uw_intraday_option_flow_bars`

First signal:

- Daily dark/lit premium z-score.
- Accumulation when large premium appears without price breakdown.
- Distribution when large premium appears but price fails to advance.

### 5. Short-Squeeze Convexity Filter

Reads:

- `uw_short_pressure_daily`
- `uw_intraday_option_flow_bars`
- existing scanner/watchlist context

First signal:

- SI/float + days-to-cover + fee/FTD pressure.
- Only activate bullish convexity when momentum and call-flow confirmation exist.
- Use as a call-spread filter, not standalone.

## Task Breakdown

### Task 1: Add Migration

**Files:**

- Create: `src/uw_scan/storage/migrations/095_uw_historical_alpha_tables.sql`

Steps:

1. Write the idempotent migration for the five tables.
2. Run `bash scripts/migrate.sh` against local DB.
3. Verify `\dt uw_scan.uw_*` or equivalent query lists all five tables.
4. Commit: `feat: add UW historical alpha tables`.

### Task 2: Add Endpoint Slugs And Fetchers

**Files:**

- Modify: `src/uw_scan/api/endpoints.py`
- Modify: `src/uw_scan/sources/uw.py`
- Modify: `src/uw_scan/normalize.py`
- Modify/Create: `src/uw_scan/models/*.py`
- Test: `tests/test_uw_historical_alpha_normalize.py`

Steps:

1. Add sample-driven tests for normalizer shapes.
2. Add endpoint slugs.
3. Add fetchers that persist raw payload/audit first.
4. Run targeted tests.
5. Commit: `feat: add UW historical alpha fetchers`.

### Task 3: Add Storage Repository

**Files:**

- Create: `src/uw_scan/storage/uw_historical_alpha.py`
- Modify: `src/uw_scan/storage/repository.py`
- Test: `tests/storage/test_uw_historical_alpha.py`

Steps:

1. Write upsert/fetch tests for each table.
2. Implement idempotent upserts.
3. Verify duplicate upserts update rows without duplicates.
4. Commit: `feat: persist UW historical alpha rows`.

### Task 4: Add Backfill CLI

**Files:**

- Create: `scripts/backfill/uw_historical_alpha_backfill.py`
- Test: `tests/backfill/test_uw_historical_alpha_backfill.py`

Steps:

1. Implement `plan` mode first; no provider calls.
2. Add `audit` mode; no provider calls.
3. Add budget counter and cap stop behavior with fake client tests.
4. Add `execute` dataset dispatch.
5. Add `resume` behavior.
6. Add `verify` report artifact under `output/uw-historical-alpha/`.
7. Commit: `feat: add UW historical alpha backfill CLI`.

### Task 5: Register Coverage

**Files:**

- Modify: `src/uw_scan/reports/data_gap_healer.py`
- Modify: `src/uw_scan/worker/jobs/data_gap_adapters.py`
- Test: data-gap registry tests if present
- Docs: `docs/runbooks/data-gap-healer.md`

Steps:

1. Add five datasets to the registry.
2. Ensure discovery fails if they are accidentally unregistered.
3. Wire heal adapters to the new CLI/job dispatch or shared backfill functions.
4. Update runbook with cap examples.
5. Commit: `feat: register UW historical alpha coverage`.

### Task 6: Add Strategy Research Assemblers

**Files:**

- Create: `src/uw_scan/reports/uw_alpha_volatility.py`
- Create: `src/uw_scan/reports/uw_alpha_gex.py`
- Create: `src/uw_scan/reports/uw_alpha_flow.py`
- Create: `src/uw_scan/reports/uw_alpha_dark_lit.py`
- Create: `src/uw_scan/reports/uw_alpha_short_pressure.py`
- Test: `tests/reports/test_uw_alpha_*.py`

Steps:

1. Add pure functions that convert persisted rows to daily feature frames.
2. Add 5d/10d/15d forward-return evaluation helpers.
3. Persist full research traces under `docs/research/` or a DB research table before process exit.
4. Commit: `feat: add UW alpha research assemblers`.

### Task 7: Run YTD Backfill With Evidence

**Files:**

- Output artifact: `output/uw-historical-alpha/<date>-coverage-report.md`
- Output artifact: `output/uw-historical-alpha/<date>-request-plan.json`

Steps:

1. Run `plan --start 2026-01-01 --end 2026-07-01`.
2. Start with `--datasets uw_volatility_signal_daily,uw_gex_levels_daily --max-uw-calls 15000`.
3. Verify coverage.
4. Continue with intraday flow and dark/lit under weekend cap.
5. Run short pressure last; it is cheap and can fill quickly.
6. Run `verify`.
7. Commit evidence docs if they belong under `docs/research/`; keep large operational output under `output/`.

## Suggested Weekend Execution Order

1. `uw_volatility_signal_daily`: ~309 calls.
2. `uw_gex_levels_daily`: ~12,772 calls.
3. `uw_short_pressure_daily`: ~412 calls.
4. `uw_intraday_option_flow_bars`: ~25,544 calls.
5. `uw_dark_lit_flow_prints`: ~25,544 calls.

Reason:

- The first three give immediate strategy research value with low/medium spend.
- The last two are high-value but high-volume; run them only while budget is truly available.

## Verification Evidence Required Before Calling It Done

- Request-plan output with expected vs actual calls.
- Per-table coverage counts:
  - expected ticker/date cells
  - filled cells
  - no-data cells
  - skipped-budget cells
  - failed cells
- Sample row check for each table.
- API usage headers captured in run metadata.
- Re-run `verify` with zero provider calls.
- At least one simple strategy frame generated for:
  - volatility anomaly / VRP
  - GEX wall distance
  - flow continuation
  - dark/lit accumulation
  - short pressure filter

