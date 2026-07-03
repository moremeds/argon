# UW daily-budget governor + RTH cadence scale-up

**Status:** implemented (feat/uw-budget-scaling, one PR). 2026-07-04.

## Problem

The whole stack shares one UW account daily counter (raised to **120k**, resets
00:00 UTC / 20:00 ET). Measured from production telemetry (`external_api_requests`
+ the `official_daily_count` response header, mini `option_wizard`):

- Live RTH stack is tiny: `full_scan` ~8.8k/day (86% of RTH spend, ~90-min
  effective cadence via the 1h freshness gate), `regime_gex_scan` ~3.5k, the rest
  <500. argon total ~16.6k/day.
- The account nonetheless **hit the 120k cap by 09:00 ET on 07-03** — deliberate
  weekend backfill (uninstrumented, ~9–15k/hr overnight) ate the whole day's
  budget before the open, and the live stack was **100% 429'd during RTH**
  (full_scan 1,266× 429, 10–11 ET was 1008/1008 rejected).

So the binding constraint is **budget allocation**, not cadence, and the failure
mode is silent starvation. Per-minute limit is effectively unlimited
(`official_minute_remaining` = 1,000,000) — only the daily total matters.

## Design

Target split under 120k: **live ~70k / research ~25k / ~20k safety margin.**

**Governor** (`sources/uw_budget.py`): reads today's (UTC-day) UW spend from
`external_api_requests`, buckets jobs into a `live` pool (`full_scan`,
`full_scan_hot`, `rescan_tick`) and a `research` pool (regime/tide/gex captures,
nightly snapshots, and all `*_backfill`), and decides `may_spend(pool)` from
per-pool ceilings + an account-wide `total_guard` (from the header, which also
sees un-instrumented/shared-key consumers). Priority ordering: live keeps going
to its ceiling; research yields first; the guard halts everything near the cap.

- Live: `full_scan` scans **hot-first** (`watchlist.hot DESC, pinned DESC`) with a
  `max_tickers` cap = remaining live budget ÷ 17 calls/ticker ÷ worker_count.
  Under pressure it drops the cold tail instead of 429-storming.
- Research: `regime_gex_scan` (and future research jobs) check `may_spend`.
- The account `total_guard` is the hard backstop and works even without backfill
  instrumentation, because live jobs capture the account-wide header.

**Hot fast lane:** per-ticker `hot` flag (migration 096), UI toggle mirroring the
pin (`HotButton` + hot-slots meter "N / max"). `full_scan_hot` job (`*/5 9-16` ET,
primary-uw-only) gives flagged tickers a tight-freshness refresh; the governor
caps overflow past `full_scan_hot_max_tickers`.

**Intraday GEX series (the non-backfillable asset):** `regime_gex_scan` expanded
to index family + M7, split RTH-fast (`*/2`) / off-hours-slow (`*/15`) weekday
cadence. UW serves GEX history only at EOD, so intraday evolution is buildable
only by live capture. `full_scan` only keeps the latest card, so the *series*
comes from gex_snapshots (this job), not full_scan.

**Phase 0:** the four UW backfill scripts route through
`ExternalApiRequestRecorder` so their spend is attributed to the research pool.

## Knobs (env)

`UW_BUDGET_GOVERNOR_ENABLED`, `UW_LIVE_DAILY_CEILING` (80000),
`UW_RESEARCH_DAILY_CEILING` (30000), `UW_TOTAL_DAILY_GUARD` (105000),
`UW_DAILY_LIMIT` (120000); `UW_SCAN_FULL_SCAN_STALE_HOURS` (0.33, float);
`FULL_SCAN_HOT_{ENABLED,CRON,STALE_MINUTES,MAX_TICKERS}`;
`GEX_SCAN_{TICKERS,RTH_INTERVAL_MINUTES,OFFHOURS_INTERVAL_MINUTES}`.

## Known soft edges

- The per-pool ceiling is a soft budget read per-pass; N sharded workers can
  transiently overshoot the live pool between snapshots. The account `total_guard`
  is the hard cap and catches this well below 120k.
- Backfill scripts are now *visible* to the governor but don't self-throttle —
  they're run deliberately. The guard still protects the live stack from them.

## Reproduce the measurements

`psql "host=100.66.147.98 dbname=option_wizard user=argon_app"` →
`external_api_requests` grouped by `job_name` / UTC-day, `MAX(official_daily_count)`
for the account counter. See the 07-02/07-03 breakdowns in the PR description.
