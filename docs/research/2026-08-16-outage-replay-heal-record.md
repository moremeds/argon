# Healing the 2026-08-11..14 outage by replay — execution record

**Executed:** 2026-08-16 · **Target DB:** mini `option_wizard` · **Window:** 2026-08-01..2026-08-16

## What the healer could see, before and after

The hardening is not "the healer got better at fixing things." It is that the
healer could not previously *express* this loss at all.

| | before | after |
|---|---|---|
| `data_gap_healer audit --start 2026-08-01` | `total_gaps = 0` | `total_gaps = 6542` |
| Datasets with a per-ticker-date audit | 12 | 22 |
| Datasets with a working adapter | 39 | 41 |
| Deep-scan tables that could be repaired at all | 0 | 10 |

Nothing about the data changed between those two audits. The 6,542 gaps were
always there; `freshness_only` simply had no vocabulary for them, and
`coverage_pct` read 1.000 because its grace window is anchored to each table's
own newest row (see the earlier `sessions_missing` work).

## Method

`pipeline.run_single_stock(market_date=...)` re-runs the nightly deep scan against
UW at a past date. One call writes nine tables, so the nine datasets wired to the
`pipeline_replay` adapter fan in to a single replay per `(ticker, date)`.

Run split across both UW workers on disjoint date windows — `execute_into_run`
takes no advisory lock (only the nightly job does), so disjoint rows parallelise
safely:

```bash
# worker uw-0
docker exec -d argon-worker-uw-0-1 sh -c "/app/.venv/bin/python \
  scripts/backfill/data_gap_healer.py execute --start 2026-08-01 --end 2026-08-11 \
  --datasets oi_by_strike,oi_change_events,greeks_by_expiry_strike,\
exposures_by_expiry_strike,exposures_summary,iv_term_snapshots,\
interpolated_iv_snapshots,max_pain_by_expiry,pcr_history \
  --max-uw-calls 40000 --confirm > /tmp/heal_a.log 2>&1"

# worker uw-1, same command with --start 2026-08-12 --end 2026-08-16
```

## Pre-flight: single-ticker smoke (AAPL, 2026-08-12)

Run before touching 170 names. All nine target tables gained rows at the
requested date; all three refused tables stayed at exactly zero:

```
OK oi_by_strike              +127     OK options_volume_daily        +0
OK iv_term_snapshots         +24      OK uw_positioning              +0
OK interpolated_iv_snapshots +9       OK short_interest_snapshots    +0
OK greeks_by_expiry_strike   +63
OK exposures_by_expiry_strike +63
OK exposures_summary         +24
OK max_pain_by_expiry        +24
OK pcr_history               +1
OK oi_change_events          +50
```

## Presence is not correctness

Row counts only prove *something* was written. The question that matters is
whether UW served that session or silently served the latest one again. AAPL
open interest, by date:

| session | call OI | put OI |
|---|---|---|
| 2026-08-07 | 3,026,067 | 2,086,807 |
| 2026-08-10 | 2,851,183 | 2,000,565 |
| **2026-08-12 (replayed)** | **2,956,523** | **2,066,171** |
| 2026-08-14 | 3,004,786 | 2,109,232 |

The replayed session is distinct from both neighbours and sits between them —
what a real intervening session looks like. Had UW ignored the date, 08-12 would
have been byte-equal to 08-14.

## Two near-misses worth recording

1. **`total_gaps: 0` from the second worker.** Worker uw-1 audited 2026-08-12..16
   and reported zero gaps — for a window measured to be empty. The cause was not
   a spine defect: only uw-0 had received the new code, so uw-1 was running the
   old registry where those datasets are still `freshness_only`. After deploying
   to both, uw-1 reported 2,983 gaps. *A code default is not deployed state, and
   this is the second time that has bitten in this repo.*
2. **`pkill` does not exist in these containers**, so the first "stopped" run kept
   going and briefly duplicated work alongside its replacement. `docker restart`
   is the reliable stop and preserves `docker cp`-ed files (they live in the
   writable layer); `docker compose up --force-recreate` would not.

## Automatic behaviour from here

`DATA_GAP_HEALER_ENABLED=true` and `DATA_GAP_HEALER_MAX_UW_CALLS=12000` are set
on the mini (verified in `/opt/argon/.env` and in-container `printenv`), so the
nightly job now heals this class of gap without intervention. With
`data_gap_healer_dataset_share=0.4` the first replay dataset draws a 4,800-call
slice ~ 320 `(ticker, date)` pairs per night; its eight siblings then cost
nothing. A 4-day, 170-name outage (~1,280 pairs) closes over roughly four nights
without starving the other ~130 datasets — resumable and self-terminating by
design.

## What is still unhealable, and why

| Table | Reason (measured 2026-08-16) |
|---|---|
| `options_volume_daily` | `/stock/{ticker}/options-volume` ignores `date` — identical body for every date |
| `short_interest_snapshots` | `/shorts/{ticker}/data` ignores `date` |
| `uw_positioning` | `/shorts/{ticker}/interest-float/v2` ignores `date` |
| `iv_rank_history` | replayable, but cockpit-only (4 tickers); a strict audit against the 170-name watchlist would invent ~166 phantom gaps per session |
| `option_contract_snapshots` | replayed and written, but the table has no date column, so it cannot carry a per-ticker-date audit |
| `dark_pool_events` | replayed and written, but keyed on `executed_at`: a name with no print that session is legitimately absent |

The first three are permanent. They are refused in code
(`uw_scan.pipeline_replay_policy`), not by convention, because all three answer
HTTP 200 with a full and plausible row set for any date requested.
