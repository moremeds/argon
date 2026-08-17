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

## Result: the outage window is closed

Measured after the replay, distinct tickers per session (all four were **0** before):

| table | 08-11 | 08-12 | 08-13 | 08-14 |
|---|---|---|---|---|
| `oi_by_strike` | 170 | 170 | 170 | 170 |
| `oi_change_events` | 170 | 170 | 170 | 170 |
| `greeks_by_expiry_strike` | 170 | 170 | 170 | 170 |
| `exposures_by_expiry_strike` | 170 | 170 | 170 | 170 |
| `iv_term_snapshots` | 170 | 170 | 170 | 170 |
| `interpolated_iv_snapshots` | 170 | 170 | 170 | 170 |
| `max_pain_by_expiry` | 170 | 170 | 170 | 170 |
| `exposures_summary` | 170 | 170 | 170 | 170 |
| `pcr_history` | 169 | 169 | 170 | 170 |

`pcr_history` at 169 on two sessions is one ticker with no `/screener/stocks` row
for that date — a legitimate absence, recorded as `no_data`, not a miss.

`option_chain_per_strike` was healed in a separate pass: the Aug runs were
launched before its adapter existed, so their in-memory registry did not include
it. That is worth noting as an operational fact — **a long-running heal holds the
registry it started with**, so a dataset wired mid-run needs its own pass.

## Addendum — the outage was the smaller half

A read-only audit widened to 2026-06-01..2026-08-16 (zero provider calls) reports
**52,750 gaps**, against 6,542 for the outage window alone:

| dataset | missing | gap_days | covered |
|---|---|---|---|
| `uw_dark_lit_flow_prints` | 5,185 | 48 | 3,813/8,998 |
| `option_chain_per_strike` | 4,455 | 52 | 4,543/8,998 |
| `pcr_history` | 3,663 | 52 | 5,335/8,998 |
| `max_pain_by_expiry` | 3,659 | 50 | 5,339/8,998 |
| `exposures_summary` | 3,648 | 51 | 5,350/8,998 |
| `oi_by_strike` | 3,010 | 50 | 5,988/8,998 |
| … 12 more | | | |

`pcr_history` and `option_chain_per_strike` appearing here at all is the
confirmation that the `date_col="snapshot_date"` fix works — both reported zero
gaps before it.

**These are not phantoms, and the distinction matters before spending budget.**
82 of the 170 active watchlist tickers were added after 2026-06-01 (56 in August),
and `oi_by_strike` tracks that growth exactly — ~103 distinct tickers per session
in June, 170+ by August. The instinct is to call the June shortfall a
lifecycle artefact of measuring today's watchlist against an older calendar.
`reconcile_watchlist_lifecycle`'s own contract says otherwise:

> **added** (new or re-added): logged; the audit in the same run then finds their
> missing history as gaps and heals it (that IS the backfill schedule).

Adding a ticker to the watchlist *is* the request to backfill its history. So the
wide window is real work — just work of a different kind from outage repair, and
far larger than one night's budget. It is what the nightly healer will chew
through over subsequent nights.

## Budget discipline during the run

The gap-healer CLI does **not** route through `sources/uw_budget`'s pool governor:
mid-run the governor reported `live_spent=2902, research_spent=3793` while UW's own
account counter stood at 60,810. Anything driven from the CLI must therefore have
its ceiling set by the operator (`--max-uw-calls`) and watched externally; the
live/research pool split will not protect the nightly captures from it.

Reserve held for this run: stop at 100,000 of UW's 120,000 daily counter. The
counter resets at 00:00 UTC and the heaviest nightly job lands near 02:00 UTC
(22,568 calls in that hour the prior night) — i.e. *after* the reset — but
`option_surface_capture` at 19:00 ET falls in the 23:00 UTC hour, before it.
Burning the last 20k would have manufactured exactly the kind of gap this work
exists to repair.

The reserve is sized from measurement, not instinct. `option_surface_capture` is
`0 19 * * 0-4` in `settings.rth_tz`, i.e. 23:00 UTC — inside the pre-reset window.
UW spend in the 22:00–23:59 UTC window on the last normal night (2026-08-10) was
**9,226 calls** (2,453 + 6,773). A 20,000 reserve carries better than 2x headroom.

## Provider errors

A burst of `UW HTTP 503 upstream connect error` accounted for 19 failed items
(~1.5%). They are transient and retryable via `resume`: a follow-up window showed
10,775 consecutive requests with zero non-200 responses.

## Finding: the LIVE path mis-dates rows on non-trading days

Not introduced by this work, and not fixed by it — recorded because the stress
test surfaced it, and it is the same defect class the replay policy exists to
prevent.

`exposures_summary` and `pcr_history` are stamped `_date.today()` on the live
path. When the nightly job runs on a weekend, UW returns the *previous session's*
data and the row is written under the weekend date:

| date | day | `exposures_summary` rows | `pcr_history` rows |
|---|---|---|---|
| 2026-08-16 | Sun | 2,907 | 170 |
| 2026-06-27 | Sat | 5,691 | 103 |
| 2026-06-20 | Sat | 5,490 | 101 |
| 2026-06-13 | Sat | 5,643 | 99 |
| 2026-06-06 | Sat | 5,820 | 104 |

Every weekend since June carries one. Under replay these same two tables are
stamped from the parameter, and the calendar spine yields trading days only, so
the replay contributed **zero** weekend rows (`oi_by_strike` and
`option_chain_per_strike` are at zero as well).

Consequences, in order of importance:

1. **The audit cannot see it.** The spine is trading-days-only, so weekend rows
   sit outside every coverage denominator — invisible to `coverage_pct`, to
   `sessions_missing`, and to the gap audit alike.
2. **A "latest row" read gets a mis-dated duplicate.** Any consumer taking
   `max(market_date)` from `exposures_summary` on a Sunday receives Friday's
   numbers labelled Sunday.

The fix has the same shape as the replay's: derive the stamp from the session the
data belongs to, not from the host clock. It touches the live nightly path, so it
is deliberately NOT bundled into this change.

## Verification that the date is honoured on OLD sessions too

The outage window is days old; the wide backfill reaches back two months, where
"does UW still serve this date" is a fair question. AAPL `oi_by_strike`, June:

| session | call OI | put OI |
|---|---|---|
| 2026-06-15 | 3,006,364 | 2,177,593 |
| 2026-06-16 | 3,040,705 | 2,184,389 |
| 2026-06-17 | 3,092,878 | 2,238,507 |
| 2026-06-18 | 3,082,227 | 2,230,889 |

Nine sessions sampled produced **nine distinct `(call_oi, put_oi)` pairs**, drifting
day to day the way open interest actually does. A repeated payload would have
produced one pair nine times.

Provider reliability over the wide window: **1 `no_data` in ~1,660 items**. UW is
serving two-month-old history essentially as well as last week's, so the backfill
buys rows rather than retries.

## What this run did NOT test

The `data_gap_healer_no_data_caveat_after` auto-caveat never fired, and that is the
correct behaviour on a healthy single pass — it requires three *consecutive*
`no_data` results for the same `(dataset, ticker, date)` across separate runs. It
therefore remains **unexercised in production**; several nightly cycles are needed
before it can be called verified. Recorded here so a future reader does not infer
from this document that it has been proven.

## Consequence of the promotion: an ~85-night nightly backlog

`data_gap_healer_start = 2026-01-01` on the mini, so from the next nightly run the
healer audits the ten newly-promoted datasets back to January. Two facts decide
whether that is productive or wasteful:

**UW serves the whole window.** Probed 2026-08-16, AAPL, distinct response hashes
and plausible row counts at every depth — there is no retention cliff here:

| date | `oi-per-strike` | `volatility/term-structure` |
|---|---|---|
| 2026-01-05 | 200, 113 rows, `5b6703f1` | 200, 20 rows, `ec486b36` |
| 2026-03-16 | 200, 116 rows, `63d5c04e` | 200, 27 rows, `028b7451` |
| 2026-05-15 | 200, 120 rows, `0ed27d27` | 200, 26 rows, `a9ec8909` |
| 2026-08-11 | 200, 127 rows, `44fc8a2f` | 200, 24 rows, `a65c52cd` |

**The backlog is therefore real work, and large.** Roughly 160 sessions x 170
tickers ~ 27,000 distinct `(ticker, date)` pairs. With
`DATA_GAP_HEALER_MAX_UW_CALLS=12000` and `dataset_share=0.4`, the first dataset
draws a 4,800-call slice ~ 320 pairs per night (its nine siblings then ride the
fan-in for free), so the queue drains over roughly **85 nights**.

Nothing overruns — the 12,000 cap is a hard bound and the run is resumable and
self-terminating. The cost is opportunity: the healer will consume its full
nightly research allowance for about three months, competing with other research
jobs for the same pool.

Three dispositions, for the operator to choose:

1. **Leave it.** Eight months of history accrues across ten datasets. Highest
   research value, longest budget commitment.
2. **Raise `DATA_GAP_HEALER_START`** (e.g. to `2026-06-01`). Drains in ~2 weeks and
   frees the pool sooner; forgoes Jan–May history.
3. **Lower `data_gap_healer_dataset_share`.** Slower drain, smaller nightly
   footprint, same eventual coverage.

Recommendation: (2) unless Jan–May options history is wanted for research, because
the outage repair — the thing that actually broke — is already complete.

## A false positive in the verification, and why it is not one

The final anti-fabrication sweep flagged `short_interest_snapshots` with 170 rows
inside 2026-08-11..14 — a refused dataset appearing to have been written. It had
not been. Attribution:

| fact | value |
|---|---|
| rows dated 2026-08-14 | 170 |
| when they were written | 2026-08-16 06:44–06:51 UTC (the Sunday live scan) |
| heal start | ~2026-08-16 15:00 UTC |
| rows written since heal start | **0** |
| rows from a `pipeline_replay` scan_run | **0** |

The refusal guard held. The query was simply too broad: `snapshot_at` on this table
is **provider-supplied**, not stamped by us, so a Sunday scan legitimately writes a
row carrying the previous Friday's snapshot date. That is honest data — and it is
precisely the opposite of the `exposures_summary` weekend case above, where the row
is stamped from `_date.today()` and therefore mislabels which session it describes.

The lesson for future verification: an anti-fabrication check must scope to the
dates the replay actually wrote AND attribute by `scan_runs.notes`, because a
provider-supplied date column will legitimately carry values inside the window.

## The most valuable find: optional bookkeeping could abort the whole heal

Both wide backfill runs died on their **first** `no_data` with

```
AttributeError: 'DataGapHealerRepository' object has no attribute 'count_recent_no_data'
```

taking roughly 27,000 queued items down with them. Healed counts plateaued while
UW spend went flat — the runs looked idle rather than dead, which is how it went
unnoticed for several minutes.

Two faults, and the second is the one that matters:

1. **Deploy miss.** `data_gap_healer_repository.py` was never copied to those
   containers, so the method the caveat path calls did not exist there.
2. **Design defect.** The call was unguarded. The auto-caveat is an
   *optimisation* — it stops the healer re-trying a scope the provider keeps
   refusing — and it was able to kill the actual repair work. The missing method
   was merely today's trigger; any DB error at that point would have done the
   same.

Fix: the block catches, logs with `repr(exc)`, and continues. The item is still
recorded as `no_data` and healing proceeds. Two tests cover it, one per failure
point (`count_recent_no_data` raising, `upsert_caveat` raising), both reproducing
the production failure before the fix.

**The pattern to watch for.** This is the second instance in one session of
*optional machinery given power over essential machinery*:

| optional feature | what it could break | how it failed |
|---|---|---|
| strict-audit column resolution | the entire dataset's visibility | returned zero gaps, reading as "fully covered" |
| no-data auto-caveat | all healing, for every dataset | raised out of the run loop |

Both passed their unit tests, because unit tests exercise a feature's happy path
rather than its blast radius on failure. Only a run against real data — where a
provider eventually answers "no rows" — put the two on a collision course. A
feature added to make the healer *more* robust is what made it fragile, and it had
never once fired in production before this run.

## Final state

| measure | value |
|---|---|
| outage window (2026-08-11..14) | **CLOSED** — 10 datasets, 170/170 tickers each |
| items healed today | 10,262 |
| replay `scan_runs` | 4,225 across 170 tickers |
| failed items | 19 (transient UW 503, retryable via `resume`) |
| UW spent | 100,946 / 120,000 — stopped by the operator guard |
| reserve held | ~19,000 for the 23:00 UTC `option_surface_capture` (measured need 9,226) |

Anti-fabrication, stated per table because the right test differs
(`docs/research/_scripts/2026-08-16-verify-replay-no-fabrication.py`):

```
OK  options_volume_daily       rows in outage window = 0   (baseline 0)
OK  uw_positioning             rows in outage window = 0   (baseline 0)
OK  short_interest_snapshots   rows from a replay run = 0
```

`short_interest_snapshots` needs run-attribution rather than a date range: its
`snapshot_at` is provider-supplied, so rows dated inside the window exist
legitimately from the live path. Checking the window alone reports a false
positive — it did, on the first pass.

The Jun–Jul backfill remains open by design (runs 87/88, ~27,000 items). It is the
nightly healer's work now.

## "Are there more gaps?" — measured answer

Three different questions hide inside that one, with three different answers.

**1. The outage — CLOSED.** 2026-08-11..14, ten datasets, 170/170 tickers each.

**2. The recent window — 6,542 -> 569.** Audit run #90 over 2026-08-01..17. Every
one of the ten replay datasets has dropped off the list except `pcr_history` with
3 (tickers with no `/screener/stocks` row). The 569 residue belongs to other
subsystems: `uw_dark_lit_flow_prints` (281), `uw_intraday_option_flow_bars` (281),
`grg_snapshots` (4).

**3. Full history since Jan 1 — 230,934.** This number is real but almost entirely
NOT loss. Two artefacts dominate it:

*Tables that did not exist yet.* First row ever recorded, for tickers on the
watchlist since May or earlier:

| table | first row | Jan–Apr sessions present |
|---|---|---|
| `oi_by_strike` | 2025-01-02 | full (20/19/22/21) |
| `iv_term_snapshots` | 2026-05-11 | 0 |
| `max_pain_by_expiry` | 2026-05-12 | 0 |
| `option_chain_per_strike` | 2026-05-13 | 0 |
| `exposures_summary` | 2026-05-21 | 0 |

`oi_by_strike` sits at 99.3% session coverage across all 155 sessions precisely
because it predates the others by 16 months. The rest are at 36–43% because
capture began mid-May; from that point their monthly session counts track trading
days.

*Tickers that were not tracked yet.* 82 of the 170 active names joined after
2026-06-01 (56 in August). Their pre-join history was never captured.

**So: nothing the desk ever recorded is missing.** What the audit reports is the
cost of extending history backwards — legitimate work (UW serves those dates,
correctly dated, verified by hash differential back to 2026-01-05) but an
investment, not a repair.

This sharpens the earlier recommendation. `DATA_GAP_HEALER_START=2026-01-01` asks
the nightly healer to reconstruct history from before these tables existed. That
is a choice worth making deliberately, not by leaving a default in place:

- **Repair-only** — set it to roughly when capture began (`2026-05-11`), and the
  queue reflects real gaps.
- **Extend history** — leave it at January and accept a multi-month, full-budget
  nightly backfill that manufactures history the desk never observed live. Legitimate
  for research, but it should be an explicit decision.

An independent corroboration of an earlier finding fell out of this: `exposures_summary`
reports 28 distinct June sessions against ~22 June trading days. The excess is the
weekend-stamping bug documented above, visible here from a completely different angle.
