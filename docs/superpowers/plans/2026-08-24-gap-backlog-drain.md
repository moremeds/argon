# Healer Repair, Then a Phase-A Gap Drain

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair the nightly data-gap healer — which today stops ~1 hour into every run,
spends UW outside the account-wide budget governor every other job respects, and reports
none of that spend — and then drain **Phase A** of the backlog: the 45,117 items dated
2026-05-01 or later. The remaining 130,038 (Jan–Apr) are **not** in this plan's scope; they
are a separate, priced decision in Task 7.

**Non-goal, stated up front so the title cannot mislead:** this plan does *not* drain all
175,155 items. An earlier draft said it did while its own scoping ruling said otherwise.

**Architecture:** No new subsystem, no new table, no migration. Durable diagnostics, then an
evidence-led fix for the stall, then the healer is put *behind the existing shared budget
governor* (`sources/uw_budget.py`) instead of its private estimate, then dataset-scoped
canaries, then the drain — executed by the **scheduled nightly job**, not by hand.

**Tech Stack:** Python 3.13 via `uv`, psycopg 3, APScheduler, Postgres schema `uw_scan`.

**Evidence labelling.** Numbers below are measured on the mini's `option_wizard` on
2026-08-24 unless marked otherwise. Two categories are deliberately *not* called
measurements: **[attributed]** — derived from UW's account-wide counter minus recorded
traffic, sound but not a direct observation of the healer; and **[estimate]** — arithmetic
on unmeasured inputs. Appendix A carries a complete, runnable query for every
decision-driving number.

## Global Constraints

- `uv run pytest` only — never bare `pytest`.
- Registry `reason` edits **must** regenerate `docs/runbooks/data-gap-dataset-policy.md`
  in the *same* commit (CI gate: `tests/unit/reports/test_data_gap_dataset_policy.py`).
- CI Guardrail 2: every `except` block references `repr(exc)`, `.exception(...)`,
  `traceback`, or `raise`.
- No mocked DB. Integration tests use the real-Postgres `seeded_db_empty_cards` fixture.
- Never fabricate a value under a historical stamp. A heal that cannot reconstruct a past
  date records honest `no_data` — never today's payload under yesterday's key.
- CHANGELOG `[Unreleased]` rides this branch before merge. Branch prefix `fix/`.
- Do not commit until the user asks. PR before main; never merge red.
- **Module-size rule applies and is already breached.** `worker/jobs/data_gap_adapters.py`
  is **1,042 lines** and `reports/data_gap_healer.py` is **2,063**; the repo rule is
  target <500, and "at 1000+ lines stop adding methods and propose a split first". Tasks 1
  and 3 both add to the 1,042-line file. **Propose the split before adding**, by domain
  seam rather than technical layer — the natural one here is: `RequestBudget` + the new
  governor wiring → its own module; `HealContext` + provider-client construction → its own;
  the `_run_*` adapters and `HEAL_SPECS` stay; the `_dispatch_*` executors → their own.
  If a task lands without splitting, it must cite this rule in the PR, per CLAUDE.md.
- **Why this is more than one PR, given "one change, one PR".** Task 1 must merge *and
  deploy* before Task 2 can observe anything — an independent prerequisite that has to ship
  first is the one exception the rule allows. Task 3 then carries the stall fix, the budget
  governor and the boundary together, because shipping any of those alone is worse than
  shipping none (D7). Tasks 4–7 are operational, not code. No other splitting is licensed.
- Secrets: read the mini's `.env` with `set -a; . /opt/argon/.env; set +a` and never echo a
  value. **Never `docker inspect --format '{{json .Config.Env}}'`** — it dumps every key in
  cleartext. `printenv <SPECIFIC_VAR>` inside the container is the safe form.

---

## Decision Record — settled 2026-08-24

### D1. This is a purchase, not a repair — and the scope follows from that

Open items by the **data date** they are missing:

| month | items | | month | items |
|---|---:|---|---|---:|
| 2026-01 | 32,340 | | 2026-05 | 20,380 |
| 2026-02 | 29,707 | | 2026-06 | 16,901 |
| 2026-03 | 34,879 | | 2026-07 | 6,906 |
| 2026-04 | 33,112 | | 2026-08 | **930** |

August contributes 0.5%. The Aug 11–14 outage this backlog gets blamed on was addressed by
PR #339 (`fix(healer): verified historical-date replay, and close the Aug 11-14 gap`). Note
what that does and does not establish: 930 residual August items and a freshness monitor
reading 50/54 tables current to the last session are *consistent* with the outage being
closed; neither proves every Aug 11–14 gap was recovered. Task 6's re-audit is what would.

Cross-cut by **when the ticker joined the watchlist**:

| joined | tickers | items | share |
|---|---:|---:|---:|
| 2026-05 | 88 | 61,150 | 35% |
| 2026-06 | 15 | 11,216 | 6% |
| 2026-07 | 11 | 11,830 | 7% |
| **2026-08** | **57** | **90,848** | **52%** |

(Sums to 175,044. The missing 111 are `grg_snapshots`, the one dataset whose items carry no
ticker, so they cannot be attributed to a join date.)

Fifty-seven names added this month carry over half the backlog, entirely as pre-membership
history. `reconcile_watchlist_lifecycle` is working as designed; the cost of that design is
what this plan is asked to pay.

**Ruling:** repair first, then drain Phase A only. See D7.

### D2. The primary defect is a ~1-hour stall, not the 429

The 429 storm is the loud failure, so the first draft of this plan was built around it. It
is not the common one. Every recent nightly run, progress measured from the items' own
`verified_at`:

| run | progress window (ET) | active | healed | failed | datasets touched |
|---|---|---:|---:|---:|---:|
| 103 | 20:02:38 → 20:52:27 | 50 min | 577 | **0** | 1 |
| 104 | 20:01:48 → 21:19:44 | 78 min | 6,689 | **0** | 2 |
| 105 | 20:02:51 → 21:26:51 | 84 min | 1,072 | **0** | 2 |
| 106 | 20:02:50 → 21:30:55 | 88 min | 1,086 | **0** | 1 |
| 107 | 08-21 20:02 → 08-22 22:55 | 27 h | 15,442 | 11,022 | 3 |

Four of five stop dead 50–88 minutes in with **zero failures**, `skipped_budget: 0`, their
cap barely touched, and **1–2 of 23 datasets** ever reached. The run row then sits `running`
and idle for ~22 hours until the next night reaps it with `no item progress in 6h`.

Run 107 is the outlier: it survived 27 hours *because* it was 429-ing — failing fast counts
as progress, so the reaper left it alone.

**Consequence.** Neither the budget fix (D3) nor the boundary fix (D5) would have healed one
extra item on runs 103–106. The stall is the blocker, it is **not yet diagnosed**, and the
containers that ran 103–107 have been recreated so their logs are gone. Tasks 2 and 3
diagnose *and fix* it before anything is drained. Four candidate causes are listed there as
things to discriminate between, not as findings.

### D3. The healer spends outside the governor every other job obeys

This is the root defect, and it is structural rather than numerical. `sources/uw_budget.py`
implements the account-wide model — `BudgetLimits`, `read_snapshot`, `may_spend`, with
`uw_daily_limit=120000`, `uw_total_daily_guard=105000`, live/research pools at 80,000 and
30,000. **`grep` for `uw_budget` across `worker/jobs/data_gap_healer.py`,
`worker/jobs/data_gap_adapters.py` and `reports/data_gap_healer.py` returns nothing.** The
healer consults none of it. It runs on a private `RequestBudget` counting `est_per_item`
units, which are not UW calls.

How wrong those units are, on one run: run 106 healed exactly 1,086 `exposures_summary`
items — 1,086 distinct `(ticker, data_date)` pairs — and claimed **2,172** calls. Its
healing ran 20:02:50 → 21:30:55 ET; over that window UW's own `official_daily_count` (from
the `x-uw-req-per-day-*` headers) moved 1 → 16,746 while every other job recorded ~481.

**[attributed]** ~16,265 real calls, ~15 per pair against an estimate of 2. UW's counter
moves only on UW calls, the healer is the only known untelemetered UW consumer, and its
progress window matches the burst minute for minute — but this is an account-counter
attribution, not a direct measurement of the healer, and it is one run of one adapter. Do
not generalise the 7.6x ratio across adapters; D7 marks where it is extrapolated.

The consequence is that `skipped_budget` reads 0 on every run: the private governor never
fires because it counts the wrong thing, and the shared governor is never asked.

### D4. The budget day is **00:00 UTC**, which is 20:00 ET only until 2026-11-01

`_nightly_uw_cap`'s comment says the UW budget day runs 20:00 ET → 20:00 ET, and the
observation supports it: `official_daily_count` resets to `1` at exactly 20:00 ET on
2026-08-20 and again on 2026-08-21. That was the obvious suspect for the 429s and it is
innocent — as far as it goes.

**It does not go all the way.** `sources/uw_budget.py` independently establishes the real
boundary as **00:00 UTC** — its `read_snapshot` buckets on `_utc_day_start`, and its
docstring records the counter dropping to 1 at `00:00:04.227Z` on 2026-08-18. Under EDT
(UTC−4) 20:00 ET *is* 00:00 UTC, so both descriptions agree today and my measurement cannot
distinguish them.

They diverge when EST resumes on **2026-11-01**: 00:00 UTC becomes 19:00 ET, so the healer's
20:00 ET cron will fire one hour *after* the budget day has already rolled, and
`_nightly_uw_cap`'s Friday/Saturday billing logic — which reasons in ET — will be attributing
spend to the wrong day for the whole winter. **Task 3c must key on 00:00 UTC, not on 20:00
ET.** Left alone this becomes a silent seasonal defect, and this plan's own D2 evidence
window is inside EDT so it would never have surfaced it.

What is separately unhandled is a run **outliving** the boundary: run 107 healed for 27 hours
across two budget days on one 90,000 cap.

### D5. One long run blocks every following night — verified in the code

`data_gap_healer_job` (`worker/jobs/data_gap_healer.py:466-478`) has two skip paths before
it audits anything: `{"skipped": "locked"}` if the advisory lock is held, and
`{"skipped": "run_active"}` if `_another_run_active` still sees a `running` row.

Run 107 was still healing at Saturday 2026-08-22 20:00:41 ET; Sunday is not scheduled
(`0 20 * * 0-5`, Mon–Sat); the latest run is still 107. Nothing has started since Friday.

**Residual unknown for Task 2:** something cancelled run 107 at 2026-08-23 05:40 ET — neither
20:00 ET nor a scheduled day. The reap sits *before* the active-run check, so whatever fired
should have gone on to create run 108, and did not. A reap that produces no successor run is
its own defect.

### D6. Do not exclude old dates on a retention theory — already disproven here

`docs/runbooks/2026-08-16-gap-heal-detached-run.md` §Retention: run 73 healed 2026-01-06
(CLSK), 2026-01-13 (HPQ), 2026-02-02 (S), 2026-02-13 (CSCO) — all older than the supposed
180-day edge — while its one `no_data` fell *inside* the safe side. Run 75's
`--start 2026-02-17` needlessly excluded ~1,340 healable ticker-dates.

Availability does not fall off a cliff. **Let the healer discover unavailability by recording
`no_data`** — and see D8, because that cuts both ways.

### D7. Cost, capacity, and the Phase-A cut

Two adapters have a real cost per heal; six do not:

| adapter | est_per_item | real | basis |
|---|---:|---:|---|
| `pipeline_replay` | 2 | ~15 | **[attributed]** D3, run 106 |
| `option_surface` | 20 | 20.1 | measured, run 75, 2026-08-16 |

**The under-count is adapter-shaped, not global — and a second run proves it.** Run 104
healed a *mixed* set: 639 `exposures_summary` pairs (`pipeline_replay`) plus 6,050
`volatility_stats_history` items (`volatility_stats`, `est_per_item=1`). Predicting from
`pipeline_replay ≈ 15/pair` and taking `volatility_stats` at its face value of 1 gives
639×15 + 6,050×1 ≈ **15,635**; UW's counter over that run's window (2026-08-18 20:02–21:19
ET, post-reset) moved to ~18,773 against ~2,000 recorded elsewhere, i.e. **~16,800
[attributed]**. Within 7%.

So: **replay-style adapters under-count badly** — one `pipeline_replay` "item" triggers a
whole `run_single_stock` — while **single-endpoint adapters are roughly honest**. Applying
the 7.6x ratio to everything, as an earlier draft did, is far too pessimistic.

| adapter | work unit | at estimate | expected | basis |
|---|---:|---:|---:|---|
| `pipeline_replay` | 14,335 pairs | 28,670 | **~215,000** | ~15/pair, two runs [attributed] |
| `option_surface` | 4,855 items | 97,100 | **~97,600** | 20.1/heal measured, run 75 |
| `uw_alpha_dark_lit` | 22,521 items | 45,042 | ~45,000 | single-endpoint, est trusted |
| `short_pressure` | 8,182 items | 24,546 | ~24,500 | single-endpoint, est trusted |
| `uw_alpha_intraday_flow` | 9,895 items | 19,790 | ~19,800 | single-endpoint, est trusted |
| `volatility_signal` | 4,615 items | 13,845 | ~13,800 | sibling of the corroborated `volatility_stats` |
| `gex_levels` | 8,275 items | 8,275 | ~8,300 | single-endpoint, est trusted |
| `flow_chain_replay` | 15,718 items | 15,718 | **15,718 – ~119,000** | *replay* adapter, unmeasured — the one real unknown |
| rest | ~600 items | ~800 | ~800 | |
| **total** | | **~254,000** | **~440,000 – ~545,000** | |

`flow_chain_replay` is the swing term and Task 4's canary settles it. Everything marked
"est trusted" is still **[estimate]** — trusted because a sibling single-endpoint adapter
came within 7%, not because it was measured.

The fan-in that makes `pipeline_replay` cheaper than it looks: its 100,478 items are 9
datasets sharing one `run_single_stock` per `(ticker, date)`, deduped by
`HealContext._replayed` to **14,335 real pairs**.

**The deployed weekday cap is the dangerous number.** `DATA_GAP_HEALER_MAX_UW_CALLS=30000`
is 30,000 *estimated* units; at the run-106 ratio that is ~225,000 real calls **[estimate]**,
far past the whole 120,000 account. It has never bitten only because the D2 stall kills the
run first — so **fixing the stall without fixing the budget turns a broken night into a
catastrophic one.** That ordering is why Task 3 is not optional.

It has already come close: on the vendor day beginning 2026-08-18 20:00 ET — one nightly
heal plus a full trading session — the counter peaked at **113,450 of 120,000**, and that day
recorded 14 HTTP 429s. Trading-day peaks run 96,244 – 113,450, so a weekday night has
single-digit thousands of real headroom. Friday and Saturday runs bill non-trading days:
that is where the account is free, and where the drain belongs.

**Ruling — Phase A only:** `data_date >= 2026-05-01`, 45,117 items, ~26% of the backlog.

**Be honest about that cut:** it is a calendar proxy, not a principle. It slices across
cohorts — the 88 names that joined in May have items back to January, and this rule keeps
four of their months for no reason intrinsic to them. The principled alternative is **heal
each ticker from its own watchlist join date forward**, the only scope that answers "what did
we actually fail to capture?" — and it would shrink the backlog to roughly the 930 August
items, i.e. nearly nothing. That is the real choice: the principled scope says the desk is
not missing data and everything past it is history being *bought*. `2026-05-01` is a
deliberate middle. An executor may substitute the join-date scope; they may not substitute a
wider one without redoing this table.

### D8. `no_data` is an outcome the drain can cheat with

D6 says let the healer discover unavailability. That creates the inverse risk: a transient
empty response, a provider degradation, a parser regression or a date-semantics bug converts
real gaps into `no_data` and the backlog "completes" without recovering anything. Run 107
already produced 42 `no_data` and nobody has looked at them.

**There is a baseline to threshold against.** Run 107's 42 are `pcr_history` (10, dated
2026-01-14 → 2026-06-04) and `uw_volatility_signal_daily` (32, 2026-01-02 → 2026-04-06), all
`reason='provider_no_data'`, all in the older half of the window. Against 15,484 items that
reached a terminal non-failure state that is a **0.27% `no_data` rate**, concentrated in two
adapters and in Phase B's date range. Phase A should see less, not more.

**Ruling:** `no_data` is provisional until confirmed by an independent second attempt on a
different day. Task 6 carries per-adapter ceilings — the 0.27% baseline is the starting
point, refined per adapter by Task 4's canaries — that **halt** the drain rather than log
past them. "Zero open gaps" is not an acceptable exit on its own.

---

## Tasks

### Task 1: Durable, visible instrumentation — **blocking, do first**

Nothing else here is verifiable until the healer's spend and progress are observable.

- [ ] `data_gap_adapters.py::HealContext.uw_client` (`:119`) and `massive_provider()`
      (`:139`) construct clients with `job_name=` but **no `telemetry_recorder`**, so
      `external_api_requests` has never held a single healer row. Thread a recorder through
      `HealContext`.
- [ ] **Two sharp edges, both checked.** `ExternalApiRequestRecorder` already owns a separate
      autocommit connection (`storage/provider_usage.py:50`), so there is no transaction
      coupling — that part needs nothing. But (a) that connection would now be held for a
      multi-hour run, which is itself one of Task 2's stall hypotheses, so reconnect on
      failure rather than assume it survives the night; and (b) `record()` swallows every
      exception and logs (`provider_usage.py:78`), so a dead recorder stops writing telemetry
      while the heal continues — the instrument fails silently exactly when Task 2 needs it.
      Surface recorder failure as a run-level counter, not only a log line.
- [ ] **Progress heartbeats at INFO, in the right place.** The worker configures
      `logging.basicConfig(level=logging.INFO)` (`worker/scheduler.py:122`), so DEBUG lines
      are discarded — a DEBUG-level trace would produce nothing. And the per-item loop is not
      in `execute_run`; it is in the dispatchers, e.g. `_dispatch_per_ticker_date`
      (`data_gap_adapters.py:873`), with different boundaries for the range and run-once
      forms. Emit one structured INFO record per item from **every** dispatcher: `run_id`,
      item id, dataset, stage (claimed → adapter entered → provider returned → marked),
      elapsed, provider calls so far.
- [ ] Heartbeats must survive container recreation — write the stage/timestamp to the
      `data_gap_items` row or `data_gap_runs.summary_jsonb`, not only to stdout. A recreated
      container's empty log proves nothing.
- [ ] Unit test: a heal through a stub UW writes an `external_api_requests` row with
      `job_name='data_gap_healer'`. **Write it failing first** — it must fail against today's
      `main`, or it is testing the stub rather than the fix.

**Acceptance:** `uw_today` on `/api/health` moves when the healer spends, and a run's last
progress stage is readable from Postgres after its container is gone.
**Counter-check:** run length and items/minute must not regress against the D2 baseline
(50–88 min, ~12 items/min). If they do, the instrument is the problem.

### Task 2: Diagnose the stall — **evidence before fixes**

- [ ] With Task 1 deployed, capture on the next real run: the last heartbeat stage and its
      timestamp, the last `external_api_requests` row, worker liveness (`ps -o pid,etime`),
      whether advisory lock `92010` is still held, and the container's `Created` time. An
      absent advisory lock proves a `running` row is a corpse.
- [ ] Discriminate between: (a) worker process death or restart, (b) a psycopg or httpx
      connection with a ~1 h lifetime, (c) the advisory-lock session dropping and the loop
      exiting quietly, (d) an un-escalated provider hang. Name which, with the evidence.
- [ ] Resolve D5's residual unknown: what fired at 2026-08-23 05:40 ET, and why the reap
      produced no successor run.
- [ ] Write the finding to `docs/research/2026-08-24-healer-stall-anatomy.md` **before** the
      fix, with its reproduce command.

**Acceptance:** the failing layer is named with evidence.

**Do not skip to a fix.** Three healer PRs (#339, #344, #352) already touched run lifecycle;
a fourth guess would be the fourth.

### Task 3: Fix the stall, and put the healer behind the shared governor

Two changes, one PR, because deploying either alone is worse than deploying neither: fixing
the stall without the budget lets a working run spend past the account (D7), and fixing the
budget without the stall changes nothing.

**3a — implement the root-cause fix from Task 2.**

- [ ] Implement the fix the evidence names. One change, addressing the cause.
- [ ] A regression test that reproduces the named failure mode and fails without the fix.
- [ ] **Halt branch:** if the cause is infrastructural (container recycling, host memory,
      Watchtower recreating a worker mid-run), this plan stops and reports. Do not absorb an
      infra fix into a healer PR.

**3b — spend through `uw_budget`, not a private estimate.**

- [ ] Route healer spend through the existing `sources/uw_budget.py` governor
      (`read_snapshot` / `may_spend`, research pool). One budget policy for the account, not
      two. Do **not** add a second hard-coded reserve.
- [ ] **Task 1 is a hard prerequisite, not merely helpful.** `read_snapshot` derives both the
      per-pool spend and the account counter *from `external_api_requests`*
      (`uw_budget.py:140-157`). A healer that writes no telemetry is not merely unobserved by
      the governor — it is arithmetically invisible to it, and would keep spending while the
      governor reports a quiet account. Wiring 3b before Task 1 ships would produce a guard
      that reads zero and permits everything.
- [ ] Check at the **provider-request** boundary, not the item boundary. An item is not
      atomic: `option_surface` costs 20.1 calls and `pipeline_replay` ~15, so an item-level
      check can cross the ceiling mid-item.
- [ ] **Fail closed on an unknown or stale counter.** `daily_count` is `None` until the first
      response; treat unknown as *stop*, never as permission, on a shared paid account. The
      live pool moves the same counter concurrently, so a cached value is stale by up to one
      request — state that bound in the code comment so nobody mistakes the guard for exact.
- [ ] Re-set the deployed `DATA_GAP_HEALER_MAX_UW_CALLS`. 30,000 estimated units is
      ~225,000 real calls **[estimate]** and must not survive this task; express the cap in
      real calls.
- [ ] Tests: missing header; stale counter; concurrent live-pool spend; per-run quota; the
      20:00 ET reset boundary.

**3c — a run stops at its own budget-day boundary.**

- [ ] `execute_run` halts when wall-clock crosses the next **00:00 UTC** after the run
      started — not 20:00 ET (D4: they are the same instant only under EDT, and part
      company on 2026-11-01).
      Remaining items stay `planned`; the run finishes `complete`, not `cancelled`. Per D5
      this is also what unblocks the following night.
- [ ] Unit test with an injected clock.

**Acceptance:** two consecutive scheduled nightly runs complete, each making progress for its
whole budget night, each stopping on quota or boundary, neither producing a
`daily_request_limit_hit` failure (run 107 produced 10,955) and neither pushing the account
counter past `uw_total_daily_guard`. `datasets_touched` > 3 is the cheap tell.
**No drain starts until this soak passes.**

### Task 4: Dataset-scoped canaries — one per adapter

Per-adapter cost does **not** fall out of a mixed drain: `external_api_requests` carries
`job_name`, `endpoint_key` and `ticker` but **no dataset or adapter column**
(`storage/provider_usage.py`), and `pipeline_replay` alone spans many endpoints. Attribution
requires scoping the run.

- [ ] One small `--datasets <one>` run per UW adapter, bounded by a **real-call** limit.
- [ ] Record per adapter: `run_id`, dataset, starting and ending `official_daily_count`,
      healed, `no_data`, failed, and real calls ÷ healed.
- [ ] Define the **verification query for that adapter specifically** — what rows should
      appear in which table for one healed item. The run-75 method (distinct `(ticker,date)`
      with `inserted_at` in the window) was valid for option surfaces; it is not a generic
      contract across fan-in replay, run-once datasets, and multi-row surfaces.
- [ ] Record the `no_data` rate per adapter — it sets Task 6's halt threshold.
- [ ] Write it all to `docs/research/2026-08-24-gap-drain-adapter-costs.md` with reproduce
      commands. A cost number not in a committed file did not happen.

**Acceptance:** every UW adapter carrying volume has a real calls/heal, a `no_data` rate, and
its own verification query.

### Task 5: Reconcile run 107 before anything new starts

- [ ] Run 107 carries 175,155 open items and a terminal state nobody set deliberately.
      Snapshot its open items, then close it. Leaving it open double-counts
      `gap_healer.open_gaps` on `/api/health` and, per D5's `_another_run_active` path, would
      block the nightly job outright.
- [ ] Do not resume it: it predates every fix and its `planned` items carry stale estimates.

**Acceptance:** exactly one non-terminal run exists, and `open_gaps` reflects one audit.

### Task 6: Drain Phase A (`data_date >= 2026-05-01`, 45,117 items)

- [ ] **The scheduled nightly job owns the drain.** Not hand-launched runs. The advisory lock
      makes a manual heal return `skipped: locked` on the nightly — which would silently
      contradict this plan's own requirement that the nightly fire every scheduled night, and
      muddle the evidence. One owner. Keep the nightly enabled and let it work.
- [ ] Scope by config (`DATA_GAP_HEALER_START=2026-05-01`) so the scheduled path drains the
      right window without a bespoke invocation.
- [ ] **Halt thresholds, from Task 4's canaries:** if an adapter's `no_data` or failure rate
      exceeds its canary baseline by a stated margin, the run stops and reports. The drain
      must not be able to complete by converting real gaps into `no_data` (D8).
- [ ] `no_data` is provisional. Re-attempt each `no_data` item once on a later day before it
      is treated as terminal, and classify the survivors.
- [ ] After each night: `verify --run-id <N>`, plus **that adapter's** verification query from
      Task 4. The healer's self-report is not evidence.
- [ ] Record each night in `docs/runbooks/` as a recovery card, following the 2026-08-16 one.

**Acceptance:** `audit --start 2026-05-01` reports zero open gaps **and** every `no_data` is
classified with a second-attempt result, **and** no night breached a halt threshold or the
account guard.

### Task 7: Phase B go/no-go — **operator decision, do not auto-start**

- [ ] Present: measured cost for Jan–Apr (130,038 items) from Task 4's real numbers, the
      weeks of weekend capacity it consumes, and what it buys — pre-membership history for
      names added May–August.
- [ ] Default recommendation is **no** unless a named piece of research needs that history.
      52% of the backlog exists because a ticker joined the watchlist in August, and no
      current consumer reads it.
- [ ] **Stop here and ask.** An executing agent must not begin Phase B on its own.

---

## Verification

| Claim | How it is proven |
|---|---|
| Healer spend is visible | `external_api_requests` rows with `job_name='data_gap_healer'` |
| Progress survives the container | A run's last stage is readable from Postgres after recreation |
| The stall is fixed | Two consecutive scheduled nights make progress for the full night |
| Budget is safe | Account counter never passes `uw_total_daily_guard`; zero `daily_request_limit_hit` |
| Runs no longer wedge | Consecutive runs `complete`, not `cancelled`; nightly fires every scheduled night |
| Rows really landed | Per-adapter verification query from Task 4, not a single generic one |
| The drain did not cheat | Every `no_data` re-attempted on a later day and classified |
| Phase A drained | `audit --start 2026-05-01` → zero open |

## Non-goals

- Draining Jan–Apr (130,038 items) without the Task 7 decision.
- WGC / COMEX / `macro_series_monthly` repair — genuine external provider blocks.
- Any "permanently lost before <date>" retention claim (D6).
- Widening `external_api_requests.provider`'s CHECK constraint — real, but not this plan.
- **The three dead gold ETFs.** GLDM/IAU/PHYS last observed 2026-03-31 (94/255/194 rows) while
  GLD is current to 2026-08-20 with 76,187; both WGC tables froze on that same 2026-03-31.
  The `etf_holdings_daily` registry reason ("requires an interactive auth cookie") describes
  WGC, whereas `sources/etf_holdings.py` reaches those three at plain public URLs with a
  browser UA and no cookie, so the reason looks copy-pasted. A shared freeze date is a reason
  to probe, not proof of a shared cause. It shares no code with the drain and touching the
  registry drags in the policy-doc regeneration gate, so it belongs in its own plan. Recorded
  here only because the same investigation surfaced it.

## Appendix A — reproduce

Every query is complete and runnable. `PSQL` expands to the authenticated psql on the mini.

```bash
PSQL='set -a; . /opt/argon/.env; set +a; export PGPASSWORD="$UW_SCAN_DB_PASSWORD";
  /opt/homebrew/bin/psql -h 127.0.0.1 -U "$UW_SCAN_DB_USER" -d "$UW_SCAN_DB_NAME" -X -f -'
```

```sql
-- D1: backlog by the data date it is missing
SELECT date_trunc('month', data_date)::date AS mon, count(*) AS todo
  FROM uw_scan.data_gap_items WHERE run_id=107 AND status IN ('planned','failed')
 GROUP BY 1 ORDER BY 1;

-- D1: backlog by when the ticker joined the watchlist
WITH todo AS (
  SELECT ticker, count(*) AS n FROM uw_scan.data_gap_items
   WHERE run_id=107 AND status IN ('planned','failed') AND ticker <> '' GROUP BY 1
), wl AS (SELECT ticker, min(added_at)::date AS added FROM uw_scan.watchlist GROUP BY 1)
SELECT date_trunc('month', wl.added)::date AS joined_month,
       count(*) AS tickers, sum(todo.n) AS gap_items
  FROM todo LEFT JOIN wl USING (ticker) GROUP BY 1 ORDER BY 1;

-- D2: how long each run actually made progress, and how many datasets it reached
SELECT run_id,
       min(verified_at AT TIME ZONE 'America/New_York') AS first_heal_et,
       max(verified_at AT TIME ZONE 'America/New_York') AS last_heal_et,
       round(extract(epoch FROM (max(verified_at)-min(verified_at)))/60) AS active_min,
       count(*) FILTER (WHERE status='healed') AS healed,
       count(*) FILTER (WHERE status='failed') AS failed,
       count(DISTINCT dataset) FILTER (WHERE status='healed') AS datasets_touched
  FROM uw_scan.data_gap_items
 WHERE run_id BETWEEN 103 AND 107 AND verified_at IS NOT NULL GROUP BY 1 ORDER BY 1;

-- D3/D4: UW's own counter by ET hour — the 20:00 reset, and the untelemetered burst
SELECT date_trunc('hour', request_started_at AT TIME ZONE 'America/New_York') AS et_hour,
       min(official_daily_count) AS cnt_min, max(official_daily_count) AS cnt_max,
       count(*) AS recorded_calls
  FROM uw_scan.external_api_requests
 WHERE provider='uw' AND official_daily_count IS NOT NULL
   AND request_started_at >= now() - interval '5 days' GROUP BY 1 ORDER BY 1;

-- D3: the healer has never written telemetry (expect 0)
SELECT count(*) FROM uw_scan.external_api_requests WHERE job_name='data_gap_healer';

-- D7: trading-day account peaks vs the 120,000 limit
SELECT (request_started_at AT TIME ZONE 'America/New_York')::date AS et_day,
       count(*) AS recorded, count(*) FILTER (WHERE status_code=429) AS h429,
       max(official_daily_count) AS vendor_peak, max(official_daily_limit) AS vendor_limit
  FROM uw_scan.external_api_requests
 WHERE provider='uw' AND request_started_at >= now() - interval '9 days'
 GROUP BY 1 ORDER BY 1;

-- D7: pipeline_replay fan-in — items vs the distinct pairs actually paid for
SELECT count(*) AS items, count(DISTINCT (ticker, data_date)) AS distinct_pairs
  FROM uw_scan.data_gap_items
 WHERE run_id=107 AND status IN ('planned','failed')
   AND dataset IN ('max_pain_by_expiry','greeks_by_expiry_strike','exposures_by_expiry_strike',
                   'iv_term_snapshots','interpolated_iv_snapshots','pcr_history',
                   'exposures_summary','oi_by_strike','oi_change_events');

-- D7: second cost data point — run 104's mixed heal, and its counter window
SELECT dataset, count(*) AS healed, sum(actual_requests) AS claimed,
       count(DISTINCT (ticker, data_date)) AS pairs
  FROM uw_scan.data_gap_items WHERE run_id=104 AND status='healed' GROUP BY 1;
SELECT date_trunc('hour', request_started_at AT TIME ZONE 'America/New_York') AS et_hour,
       min(official_daily_count) AS cnt_min, max(official_daily_count) AS cnt_max,
       count(*) AS recorded
  FROM uw_scan.external_api_requests
 WHERE provider='uw' AND official_daily_count IS NOT NULL
   AND request_started_at >= '2026-08-18 20:00 America/New_York'
   AND request_started_at <  '2026-08-18 23:00 America/New_York'
 GROUP BY 1 ORDER BY 1;

-- D8: the no_data baseline
SELECT dataset, count(*), min(data_date) AS lo, max(data_date) AS hi, min(reason) AS reason
  FROM uw_scan.data_gap_items WHERE run_id=107 AND status='no_data' GROUP BY 1;

-- D8 / Non-goals: gold ETF coverage
SELECT ticker, max(obs_date) AS last_obs, count(*) AS rows
  FROM uw_scan.etf_holdings_daily GROUP BY 1 ORDER BY 2 DESC;
```

```bash
# D3: the healer never asks the shared governor (expect no output)
grep -rn "uw_budget\|may_spend\|read_snapshot" \
  src/uw_scan/worker/jobs/data_gap_healer.py \
  src/uw_scan/worker/jobs/data_gap_adapters.py \
  src/uw_scan/reports/data_gap_healer.py
```
