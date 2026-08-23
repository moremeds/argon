# Fundamental Lane — Calendar-Driven Ingest and Filing-Date Recovery

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move statement ingest from a monthly blind sweep of 450 names to a daily
calendar-driven pull of the ~6 names that actually reported, and repair the two defects
that are stripping `filing_published_at` from the panel — the field the one validated
fundamental signal is measured on.

**Architecture:** One PR against the existing `fundamental_*` modules. No new table, no
new subsystem. Two endpoint slugs, one new job, one tolerance rule, one `ON CONFLICT`
clause, one config cron.

**Tech Stack:** Python 3.13 via `uv`, psycopg 3, APScheduler, Postgres schema `uw_scan`.

**Measurement backing every number here:**
`docs/research/2026-08-23-fundamental-filing-date-recovery/VERDICT.md`

## Global Constraints

Same as `2026-08-13-fundamental-lane-next.md` — `uv` only; never commit without an
explicit request; PR before main, never merge red; no `Co-Authored-By` trailers;
CHANGELOG rides the branch; idempotent migrations; never extend `storage/repository.py`;
<500 lines/file; persist every research trace; worktrees under `.worktrees/`.

---

## Decision Record — settled 2026-08-23

### D1. The user's proposal is validated, and needs no retry window

"If a company reports today, pull it today" works: statements are retrievable the day of
the report. 100% landed for reports 2–7 days old, 98.5% overall across 704 report events.
All 10 non-landed events are ≥10 days old and permanently non-landed for three reasons
that are not timing (no history at all; a panel that stopped advancing; 12-week fiscal
filers). VERDICT F3.

The lookback that survives in this design is **outage insurance only** — it exists so a
day the worker was down is picked up the next day, not because UW publishes late. It is
deliberately small (3 days) and that number is not a measurement, it is a weekend.

### D2. The monthly sweep is NOT replaced. It is demoted to backstop, and it earns it twice

`premarket` + `afterhours` are the *classified* calendar. A name whose `report_time` UW
has not classified appears in neither — verified for ISRG, SONY, DJCO, POET, all of which
return `report_time: "unknown"` and are absent from their own report date's calendar
despite 61–257 other names being listed that day. There is no market-wide calendar
endpoint on our tier. Blind spot ≈2% of the statement-bearing universe. VERDICT F4.

The sweep is also the only thing that re-pulls a period long after first ingest, which is
what delivers a filing date that breakdown publishes late (D4). Two independent jobs
justify keeping it; neither alone would.

### D3. Filing dates are missing because we ask with the wrong key

`_filing_dates()` keys breakdown rows by their true fiscal period end and looks them up
with the statement endpoints' calendar-month-end period. AAPL's Q3 is `2026-06-27` in
breakdown and `2026-06-30` in statements. For every 52/53-week filer the lookup misses on
every period, forever — 129 tickers, 885 periods, **0** matched at tolerance 0.

Breakdown is not missing the data: it dates 100% of what it carries (AAPL 69/69).

**±7 days**, chosen from the curve, not from taste: it recovers 592 periods / 1,785
statement rows, 98.5% of everything reachable at any tolerance, and **0 of the 885
periods matched two breakdown rows** — quarters are ~91 days apart, so the window cannot
reach a neighbour. VERDICT F1.

### D4. A late-arriving filing date is currently discarded, and that is a separate defect

`record_statements` ends `ON CONFLICT ... DO UPDATE SET last_seen_at = now()`.
`filing_published_at` is not in the SET, and `content_hash` deliberately excludes it, so a
re-pull carrying a newly-published date collides on an identical hash and updates only the
timestamp. Breakdown's frontier trails statements for 7 of a random 40 names (INFY 91
days, GFS 181), so this path is live. VERDICT F2.

**Fill only NULL → value.** An existing non-NULL date is a recorded fact about an
immutable observation and must not be silently overwritten; a disagreement is logged, not
applied. Widening this to unconditional overwrite would make the column mean "whatever the
provider said most recently", which is not what any consumer of PIT data can use.

### D5. Cost falls. This is not a freshness-for-budget trade

~30 UW calls/day (≈900/month) against the monthly sweep's 1,800/month. Keeping the sweep
as backstop lands the total near 2,700/month, against a 120k/day budget. VERDICT F5.

### D6. What this plan does not claim

Nothing here improves the *signal*. The composite still orders names cross-sectionally and
still cannot time one name against itself. This plan makes the panel's point-in-time dating
correct and its freshness daily; whether a better-dated panel measures differently is a
question for a later re-run of the IC measurement, not a claim of this plan.

---

## File Structure

```
src/uw_scan/api/endpoints.py                     MODIFY  two calendar slugs
src/uw_scan/sources/earnings_calendar.py         NEW     fetch + paginate the calendar
src/uw_scan/worker/jobs/fundamental_ingest.py    MODIFY  tolerant period match
src/uw_scan/worker/jobs/fundamental_ingest_daily.py NEW  calendar -> universe -> ingest
src/uw_scan/storage/fundamental_obs.py           MODIFY  fill NULL filing dates on conflict
src/uw_scan/worker/scheduler.py                  MODIFY  register the daily job
src/uw_scan/config.py                            MODIFY  cron + enable + lookback knobs
tests/unit/...                                   NEW     frozen-fixture tests
CHANGELOG.md                                     MODIFY  [Unreleased]
```

---

## Task 1: Tolerant filing-date match

- [x] Failing test: an AAPL-shaped fixture (statement `2026-06-30`, breakdown `2026-06-27`
      / `2026-07-31`) resolves the filing date; today it resolves `None`.
- [x] Implement nearest-within-7-days resolution in `fundamental_ingest`, exact match first.
- [x] Test that a 30-day-away breakdown period does NOT match (the window is a window).
- [x] Test that ambiguity is impossible at ±7 given ~91-day quarters — nearest wins,
      deterministically, and the tie path is covered.

## Task 2: Stop discarding late filing dates

- [x] Failing test: `record_statements` twice, first with `filing_published_at=None`,
      then with a date, same payload → the date is stored. Today it is not.
- [x] `DO UPDATE SET last_seen_at = now(), filing_published_at = COALESCE(existing, new)`.
- [x] Test the guard: an existing non-NULL date is NOT overwritten by a different one.

## Task 3: The earnings calendar source

- [x] Register `EARNINGS_PREMARKET` / `EARNINGS_AFTERHOURS` slugs.
- [x] `sources/earnings_calendar.py`: fetch one date, both slots, paginated — peak days
      returned 202 and 257 rows, so a single page silently truncates.
- [x] Test pagination against a frozen two-page fixture.

## Task 4: The daily job

- [x] `fundamental_ingest_daily`: for each date in `[today - lookback, today]`, collect
      calendar symbols, intersect with the `ranked` universe, call `fundamental_ingest`
      with that ticker list. Self-gates to zero calls when the intersection is empty.
- [x] Register on `uw-0` (it spends UW budget), gated by config, with a lookback default
      of 3 days.
- [x] Keep `fundamental_ingest` (monthly) registered and unchanged — D2.

## Task 5: Backfill the recovered dates — BLOCKED ON DEPLOY

Verified locally instead: `fundamental_ingest(tickers=['AAPL'])` through the
scheduler's own helpers took AAPL from 222 NULL filing dates to 42 (180 filled,
matching the run's `filing_date_tolerance` counter exactly), with `inserted: 0` —
no phantom restatements. The prod delta still needs the image on the mini.

- [ ] Re-run the monthly ingest once against prod after the fix and record the delta in
      `filing_published_at IS NULL` counts. Expected: ~592 periods / ~1,785 rows filled.
- [ ] Record before/after in the CHANGELOG entry and the research VERDICT.

## Open questions to resolve during execution

1. **Does the ±7 tolerance ever fire on a name where exact matching already worked?**
   It should not — exact is tried first — but the run should log tolerance hits so the
   rate is observable rather than assumed.
2. **Does the calendar's blind spot drift?** Re-run `coverage_probe.py` after a quarter;
   if the ~2% grows, the backstop's cadence is the lever.
3. **Does a better-dated panel change the composite's measured IC?** Out of scope here;
   the re-measurement becomes possible once Task 5's backfill lands.
