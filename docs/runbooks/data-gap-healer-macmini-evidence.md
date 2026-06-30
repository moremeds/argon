# Data gap healer — end-to-end evidence

Captured 2026-06-30 against the local persistent dev DB `option_wizard_local`
(127.0.0.1), which had every migration through `092` applied via
`bash scripts/migrate.sh`.

## Why local, not the mini (yet)

Migration `092` reaches the mini's `option_wizard` only through a **release tag**
(the mini's prod DB is writer-restricted to the launchd stack, and the
three-tier isolation tripwire blocks a macbook write to `option_wizard`). So the
pre-merge evidence runs against `option_wizard_local`. The macmini run is the
post-deploy step below.

The mini's manual option-surface backfill (`PID 75761`) was left running and
untouched throughout (UW `daily=18556/60000` at capture time).

## Evidence (local, real persistent DB)

### 1. `verify-all` — full audit, read-only

```
verify-all --start 2026-01-01 --json
```

- `run_id=1`, **`unregistered_tables=0`** (all 117 datasets registered)
- `registry_count=117`
- **`budget_spent={}` and `heal_outcome={}`** → zero provider calls (audit is read-only)
- audit-mode buckets (every table in exactly one): `strict_ticker_date=7`,
  `strict_session=3`, `freshness_only=67`, `provenance=13`,
  `operational_state=1`, `research_artifact=26` → 117 total
- `total_gaps=41458` (sparse dev DB). Top: `option_surface_grid_daily=12200`,
  `volatility_stats_history=10781`, `greek_exposure_daily=4257`,
  `vrp_daily=3702`, `realized_volatility_history=3702`, `daily_ohlc=3694`
- report artifact written: `output/data-gap/2026-06-30-gap-report.{md,json}`

### 2. `execute` (DB-to-DB) — clean run, zero UW

```
execute --datasets market_tide_sentiment_daily --start 2026-06-23 --confirm   # run 2
execute --datasets vrp_daily --start 2026-06-01 --end 2026-06-05 --confirm     # run 3
```

Both completed (`status=complete`), `budget_spent` all zero. Both windows were
already fully covered locally → `outcome={}` (nothing to heal — the correct
"no work" result).

### 3. `execute` — heal-attempt → honest `no_data` (the verifier guard)

```
execute --datasets vrp_daily --start 2026-02-07 --end 2026-02-07 --confirm      # run 4
```

- `outcome={'no_data': 100}`, `budget_spent` all zero
- The executor claimed 100 `vrp_daily` items, ran the vol-analytics rollup (db
  provider, no UW), verified each at `2026-02-07`, and — because the rollup could
  not reconstruct that date — recorded honest `no_data`. **A heal is never marked
  healed until the row is actually present.**

## Known limitation surfaced by this run

`2026-02-07` is a **Saturday**. The self-calendar (union of dates any source
table has, plus the `market_tide_sentiment_daily` reference) can include a
non-trading day when a source table holds a stray weekend row, producing
spurious "gaps" for the full watchlist. These verify as `no_data` (harmless, no
false heal), but they are noise. Fix path: gate the calendar with a real
exchange calendar (`pandas_market_calendars` or an `index_ohlc_daily`-derived
trading-day set). Tracked as a follow-up; out of scope for this PR.

## Macmini run (post-deploy)

After this branch is released and the mini deploys `092`:

```bash
# 1. dry full audit — expect unregistered=0, zero provider calls
UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard \
  uv run python scripts/backfill/data_gap_healer.py verify-all --start 2026-01-01 --json

# 2. limited DB-to-DB execute (no UW spend)
UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard \
  uv run python scripts/backfill/data_gap_healer.py execute \
    --datasets market_tide_sentiment_daily,vrp_daily,stock_analytics_daily,realized_volatility_history --confirm

# 3. re-run verify-all, record before/after total_gaps
```

Do **not** run a UW-heavy execute while `PID 75761` (or any manual UW backfill)
is active. Flip the nightly job on only after these manual runs look right:
`DATA_GAP_HEALER_ENABLED=true` in the mini `.env`, then kickstart the uw-0 worker.
