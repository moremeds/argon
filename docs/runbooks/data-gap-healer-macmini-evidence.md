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

### `volatility_stats_history` — YTD backfill (UW, in progress)

`volatility_stats_history` only accumulated forward from its 2026-05-11
inception (the fetcher was current-snapshot-only). The new `volatility_stats`
adapter + `fetch_volatility_stats(market_date=…)` backfills it from UW, one call
per (ticker, date).

- **As of 2026-06-30 06:24 ET: 6,091 / 9,397 YTD cells healed (64.8%).** Real UW
  `iv` / `rv` / `iv_rank` for pre-inception dates (validated against live UW).
- The remaining **3,306 cells** are deferred to the **20:00 ET nightly** (which
  runs at the 00:00 UTC UW reset, on a fresh 60k budget, off RTH) rather than
  spent now — the manual backfill was capped to keep **≥25k UW reserved for
  regular trading hours** (UW was at `33,505/60,000` at capture).

## Macmini operational follow-ups (post-deploy)

After the release deploys `092`/`093` to the mini:

1. **Finalize the manual backfill run** (`data_gap_runs` id=6 is left `running`
   from the capped session) so the nightly's `_another_run_active` guard does not
   skip — it skips while any `mode='execute'` run is `running`.
2. **Enable the nightly:** `DATA_GAP_HEALER_ENABLED=true` in the mini `.env`,
   then kickstart the `uw-0` worker (env is frozen at fork). The 20:00 ET run
   then audits + heals under the 20k UW cap, which finishes the vol_stats tail
   automatically on fresh budget.
3. **Watch the first nightly run** — the scheduled-job path (cron + advisory lock
   + refresh adapters + evidence write) is test-covered but had not run in prod
   before this enable. Flip the flag back off if it misbehaves.

Do **not** run a UW-heavy manual `execute` while another manual UW backfill (e.g.
the option-surface capture) is active.
