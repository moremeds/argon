# Data gap healer — end-to-end evidence

Two captures: (1) a pre-merge functional run against the local persistent dev DB
`option_wizard_local`, and (2) the **real macmini run** against the prod DB
`option_wizard` (where migration `092` was applied manually so the live evidence
could be captured before the release tag re-runs it as a no-op).

Registry currently holds **118 datasets** (the local capture below predates the
118th, `watchlist_ticker_events`, which was added later in this same branch).
Audit-mode buckets (every table in exactly one): `strict_ticker_date=7`,
`strict_session=3`, `freshness_only=67`, `provenance=14`, `operational_state=1`,
`research_artifact=26` → **118 total**.

## Part 1 — local functional evidence (`option_wizard_local`, 127.0.0.1)

Captured 2026-06-30, every migration through `092` applied via
`bash scripts/migrate.sh`.

### 1. `verify-all` — full audit, read-only

```
verify-all --start 2026-01-01 --json
```

- `unregistered_tables=0` (every temporal table registered — the CI discovery gate)
- **`budget_spent={}` and `heal_outcome={}`** → zero provider calls (audit is read-only)
- report artifact written: `output/data-gap/2026-06-30-gap-report.{md,json}`

### 2. `execute` (DB-to-DB) — clean run, zero UW

```
execute --datasets market_tide_sentiment_daily --start 2026-06-23 --confirm   # run 2
execute --datasets vrp_daily --start 2026-06-01 --end 2026-06-05 --confirm     # run 3
```

Both completed (`status=complete`), `budget_spent` all zero. Already-covered
windows → `outcome={}` (the correct "no work" result).

### 3. `execute` — heal-attempt → honest `no_data` (the verifier guard)

```
execute --datasets vrp_daily --start 2026-02-07 --end 2026-02-07 --confirm      # run 4
```

- `outcome={'no_data': 100}`, `budget_spent` all zero
- The executor claimed 100 items, ran the vol-analytics rollup (db provider, no
  UW), verified each at `2026-02-07`, and — because the rollup could not
  reconstruct that date — recorded honest `no_data`. **A heal is never marked
  healed until the row is actually present.**

## Part 2 — macmini prod run (`option_wizard`, 100.66.147.98)

Real captures against the live prod DB, 2026-06-30.

### Calendar fix — the headline correction

The self-union calendar (each dataset's own dates ∪ the `market_tide` reference)
let a stray weekend/holiday source row manufacture a full-watchlist phantom gap.
Switching the expected-session calendar to the clean `market_tide_sentiment_daily`
trading-day spine (0 weekend/holiday rows) cut the full audit:

- **`total_gaps` 25,814 → 15,021** on the same prod data, same window.
- `vrp_daily` / `realized_volatility_history` / `stock_analytics_daily` each
  collapsed from ~3,000–3,800 phantom gaps to their **2 genuine misses each**.

### Verifier proven honest under heal

A heal run over the phantom (non-trading-day) gaps recorded
`outcome={'no_data': 20113}` — **zero false heals**. The strict `COUNT` at each
row's own date refused to mark anything healed that a provider could not serve.

### `daily_ohlc` — fully healed, zero UW

Massive (uncapped) backfilled `daily_ohlc`: **3,764 healed, 101 free massive
calls, 0 UW spend**; re-audit `missing=0`.

### `volatility_stats_history` — YTD backfill (final)

`volatility_stats_history` only accumulated forward from its 2026-05-11
inception (the fetcher was current-snapshot-only). The new `volatility_stats`
adapter + `fetch_volatility_stats(market_date=…)` backfills it from UW, one call
per (ticker, date).

- Manual backfill (2026-06-30, runs 6+7): **7,503 / 9,397 YTD cells healed
  (79.8%)**, capped to keep ≥25k UW reserved for RTH (UW at `33,505/60,000` at
  cap).
- Remaining **1,894 cells** deferred to the 20:00 ET nightly on a fresh 60k
  budget.
- First nightly (run 9, 2026-07-01): the 20k UW cap was fully consumed by the
  concurrent `option_surface_grid_daily` backlog (1,735-item historical gap since
  PR #145 deploy, ~12 UW calls/item). The 788 `volatility_stats_history` cells
  that remained were claimed but `skipped_budget`. They carry forward to the next
  nightly automatically (re-audited fresh each run). See "First nightly" section
  below.

## Part 3 — First prod nightly run (run 9, 2026-07-01)

Run 9 fired at 08:00 HKT (20:00 ET June 30) — the correct scheduled slot.

```
status:   complete
started:  2026-07-01T08:00:00+08:00
finished: 2026-07-01T13:01:33+08:00
healed:         1,000
no_data:          125
skipped_budget: 1,727
budget_spent.uw: 20,000  (cap hit exactly)
```

### What was healed

All 1,000 healed items were `option_surface_grid_daily` (the EOD option surface
grid from PR #145). The 20k cap was exhausted on this dataset alone — each
(ticker, date) item requires ~12 UW calls (`/greek-exposure/expiry` + one call
per active expiry).

### Refresh adapters (all re-runnable datasets)

All 15 refresh targets ran after the heal phase. One failure:
`rates_treasury_auctions` — this is a known fragile FRED/Treasury endpoint (not
a healer bug). One budget skip: `uw_gold_options_daily` (UW budget was at zero
when the refresh phase ran). All others: `refreshed`.

### Remaining open gaps (post-run audit)

| Dataset | Missing | Notes |
|---|---|---|
| `option_surface_grid_daily` | 1,735 | historical backlog from Apr 20; ~12 UW/item; nightly will reduce by ~1,600/night at 20k cap |
| `volatility_stats_history` | 788 | 1 UW/item; should close in one nightly once option_surface backlog shrinks |
| `greek_exposure_daily` | 202 | single-name GEX backlog; a few UW/item |
| `top_net_impact_snapshots` | 121 | session-scoped; 1 UW/call |
| `vrp_daily` / `stock_analytics_daily` / `realized_volatility_history` | 2 each | likely genuine unhealable gaps (no source data for those dates) — seed caveats after confirming |

### Watchlist lifecycle baseline

First run logged all 103 active tickers as `added` — correct one-time baseline
behaviour for a fresh `watchlist_ticker_events` table. Future nightlies log only
diffs (new additions / removals).
