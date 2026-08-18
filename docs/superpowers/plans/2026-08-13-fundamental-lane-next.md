# Fundamental Lane — Next Work Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Widen and keep fresh the panel behind the one validated fundamental signal, verify that signal is actually accumulating in production, and capture the revenue-breakdown series before it can age out — while shipping concentration as descriptive context only, with no edge claim.

**Architecture:** Three independent PRs against the existing `fundamentals/` package and `fundamental_*` tables. No new subsystem. PR-1 is data/config plus one cron. PR-2 is an ops verification that may need no code. PR-3 adds one PIT observation table, one quarterly capture job, and one card block.

**Tech Stack:** Python 3.13 via `uv`, psycopg 3, APScheduler, Postgres schema `uw_scan`, Next.js 16 + React 19 (hand-rolled SVG).

## Global Constraints

- `uv` only — `uv run pytest`, never bare `python`/`pip`.
- Never commit without an explicit user request. Draft first, wait.
- Always open a PR before merging to main. `git push origin main` is forbidden. Never merge before CI is green.
- No `Co-Authored-By: Claude` trailers.
- CHANGELOG `[Unreleased]` entry rides the feature branch, before merge.
- Migrations are idempotent (`IF NOT EXISTS`, `ON CONFLICT DO NOTHING`); no tracking table.
- A new temporal table needs a `DatasetRegistryEntry` **and** a regenerated dataset-policy doc, in the same feature PR — two CI gates.
- Module size budget: target <500 lines/file; propose a split at 1000+.
- Never extend `storage/repository.py`; new domains get their own `storage/<domain>.py`.
- Persist every research trace before the process exits; stdout-only is data loss.
- Smoke tests run the real worker path: API/enqueue → DB row → worker claims → DB result → web renders. Never a `/tmp` script calling the function directly.
- Worktrees live in `.worktrees/<branch-slug>/`.

---

## Decision Record — what was settled on 2026-08-13

This section is the durable record of the conversation that produced this plan. It is not
implementation guidance; it exists so a later reader does not re-litigate a closed question.

### D1. P4 was killed by a broken probe, not by the data

`docs/research/2026-08-12-fundamental-segment-computability/VERDICT.md` reported **geography
0/257** and closed the concentration ledger. That zero was an artifact of three grouping bugs.
NVDA's geographic breakdown reconciles to the cent against the untagged consolidated total.

Re-measured over 401 tickers with a ≥6-computable-periods gate the original probe never
applied: **segment 184 (45.9%), geography 128 (31.9%)**. 181/184 and 124/128 are computable in
≥6 of their last 8 periods. Full method, the three bugs, and the level-selection rule:
`docs/research/2026-08-13-fundamental-concentration-axis/VERDICT.md`.

### D2. Concentration ships as description, never as a scored input

At spec §896's weight 0.10 it would put a hole in half the names, so composites stop being
comparable across names — and the composite is already measured not to pay. As a cited card
block, partial coverage is what spec §964 already designed for (absent → `na`, never 0).

**Spec §896's `✅ UW rev_breakdown, 24/25` line is wrong on two counts** — it conflates coverage
with computability, and it assigns a composite weight this plan withdraws. Correcting it is a
task in PR-3.

### D3. Concentration is not an edge, and this is measured

| finding | value |
|---|---|
| quarter-over-quarter \|Δ top share\| | median **1.20pp** (segment), 1.15pp (geography) |
| full range across a name's entire history | median **6.90pp** (segment), 5.14pp (geography) |
| annual/quarterly basis contamination | median **2.5pp**, p90 **17.5pp**, 35.5% exceed 5pp |
| panel depth | **8 quarters**, starting 2024-09 for 218 of 222 eight-period names |

The measurement error is ~2× the median quarterly step and its p90 exceeds the median name's
entire observed range. The level, which survives the noise, is near-static. A public,
filing-lagged, highly persistent characteristic becomes a factor loading, not alpha — a claim
this lane has already demonstrated, since the composite orders names correctly and does not pay.

**No returns backtest is planned or justified.** If an edge is ever tested it should be against
**vol** — does concentration predict realized-vs-implied around earnings — on the options
surface, which is this desk's structural-advantage ground. That test is also underpowered today
(`option_surface_grid_daily` spans 2025-12-26→present, ~2–3 earnings cycles) and gets stronger
every quarter both panels accrue.

### D4. Capture is justified by accrual optionality, not by value

All 222 eight-period tickers share an oldest period of 2024-09. A **fixed start date** and a
**rolling 8-quarter window** are indistinguishable from a single snapshot. Under that
uncertainty the asymmetry is decisive: capture costs ~401 UW calls per quarter against a
120k/day budget; not capturing risks permanently losing history that cannot be reconstructed —
the same argument `CLAUDE.md` already makes for `option_surface_grid_daily`. Storing snapshots
is itself the discriminating test: watch whether the oldest period moves.

### D5. ~~Widening the universe is worth less than it first appeared~~ — OVERTURNED 2026-08-18

**This decision was wrong, and the error was measuring the wrong host.** It is kept in full
below rather than deleted, because the mistake is the reusable part.

The scoring pipeline has **zero failures on its input** — every one of the 257 universe names
has statements and a score; 144 tickers have statements and no membership. But the valuable
output is the valuation band, and the band needs unadjusted daily closes from the local lake:

| | has `1d.parquet` |
|---|---|
| the 257 universe names | **254/257** (exactly matches `valuation_anchors`' 254 tickers) |
| the 144 excluded names | **29/144** (measured on the MacBook mirror) |

~~So widening yields **+144 composite scores (the part that does not pay) and +29 valuation bands
(the part that does)** — 254 → 283, about +11%, not the +56% panel width the raw counts suggest.
The real gate on the valuable half is **lake price depth**, not universe membership.~~ The 144 are
the capex-research cohort and were never breadth-probe candidates, so their depth was never
assessed. ~~The mini's mirror may be deeper; apex returned 502 when probed, so this is unverified.~~

**Re-measured on the mini** — the host that actually computes the bands, whose mirror holds 14,689
equity symbol directories against the MacBook's 653. Full method and per-ticker trace:
`docs/research/2026-08-18-fundamental-lake-depth/VERDICT.md`.

| the 144 excluded names | MacBook | mini `/lake` |
|---|---:|---:|
| has `1d.parquet` | 29 | **141** |
| price depth ≥ 12 quarters (`MIN_HISTORY`) | 23 | **132** |
| price depth ≥ 20 quarters (`WINDOW_QUARTERS`) | 21 | **120** |
| statement depth ≥ 12 quarters | 143 | 143 |

So widening yields **up to +132 valuation bands, not +29** — 254 → up to 386, about **+52%**. The
raw panel-width figure this decision dismissed was approximately right, and **the gate is universe
membership after all, not lake depth**. PR 1 is worth roughly 4.5× what this plan credited it with.

132 is an upper bound: clearing the depth gate is necessary, not sufficient, because the method also
refuses on non-positive EV, a non-positive numerator, and a stale filing. The universe cohort
converts at 99.2% (256 clear the gate, 254 bands exist), but that rate must not be transferred — the
144 carry more unprofitable and negative-EV names, which is exactly what the EV guard catches. **PR 1
must therefore report the realised band count as its verification rather than assert one up front.**

Two lessons, both already paid for once in this lane:

- **counting files is coverage, not computability** — the identical conflation produced the retracted
  `0/257` concentration verdict in D1, one round earlier;
- **name the host in any coverage number.** "Measured on the MacBook mirror" was recorded honestly
  here and still produced a wrong decision, because the caveat was not treated as a blocker. A
  measurement whose host makes it wrong is not a measurement with a caveat.

### D6. The alert pipeline is deprioritised — a recorded deviation

Per user direction, alert pipeline v1 is dropped in favour of extending the model. `CLAUDE.md`
names the signal→alert pipeline as Stage 1's *minimal deliverable*, so this is a deviation from
the master plan, recorded here deliberately rather than left implicit.

---

## File Structure

| File | Responsibility | PR |
|---|---|---|
| `scripts/seed_fundamental_universe.py` | modify — admit statement-bearing names under a stated reason | 1 |
| `src/uw_scan/worker/scheduler.py` | modify — wire the quarterly statement ingest | 1 |
| `src/uw_scan/config.py` | modify — ingest cron + enable flag; PR-3 capture flags | 1, 3 |
| `src/uw_scan/storage/migrations/122_revenue_breakdown_obs.sql` | create — PIT breakdown observations. Was `120`; renumbered 2026-08-18 because `120_freshness_sessions_missing.sql` landed on `main` and the unmerged macro branch already claims `116`/`119`/`121`. A duplicate prefix is a CI gate — re-check the next free number when PR 3 actually starts. | 3 |
| `src/uw_scan/fundamentals/concentration.py` | create — axis grouping, level selection, annual detection | 3 |
| `src/uw_scan/storage/fundamental_concentration.py` | create — its own storage module, not `repository.py` | 3 |
| `src/uw_scan/worker/jobs/fundamental_concentration_capture.py` | create — quarterly capture job | 3 |
| `src/uw_scan/api/routers/fundamental.py` | modify — read-only concentration block | 3 |
| `web/components/stock/panels/FundamentalConcentration.tsx` | create — descriptive card block | 3 |
| `src/uw_scan/reports/data_gap_healer.py` | modify — `DatasetRegistryEntry` for the new table | 3 |
| `docs/superpowers/specs/2026-08-10-fundamental-pm-agent-design.md` | modify — correct §896 | 3 |

---

## PR 1 — Panel width and freshness

**Branch:** `feat/fundamental-panel-width-freshness`

Two changes that belong together: they share the same tables, the same verification (panel
width and recency), and neither is independently worth a review cycle.

### Task 1: Admit statement-bearing names to the `ranked` tier

**Files:**
- Modify: `scripts/seed_fundamental_universe.py`
- Test: `tests/scripts/test_seed_fundamental_universe.py`

**Interfaces:**
- Consumes: `fundamental_statement_obs` (401 distinct tickers), `universe_breadth.json`
- Produces: `fundamental_universe` rows with a `reason` that distinguishes the three provenances

The seeder currently derives `ranked` from the breadth probe's gates, which include **local lake
price depth** (≥2500 bars starting ≤2013-01-01). That gate exists because the probe needed
forward returns to validate against — it says nothing about a name's fundamentals. The seeder's
own docstring already makes this argument to admit the 12 core names: *"Statement ingest reads UW
and never touches the lake, so that limit does not apply here."* Task 1 extends the same
reasoning to every name that already has statements.

**The `reason` column must keep the three groups separable.** 245 names carry validation
backing, 12 are core names seeded past the price gate, and the new ~144 are the capex-research
cohort with no validation backing at all. A later reader must not collapse these into one claim.

- [ ] **Step 1: Write the failing test**

```python
def test_seeder_admits_statement_bearing_names_with_distinct_reason(seeded_conn):
    rows = fetch_universe(seeded_conn, tier="ranked")
    reasons = {r["ticker"]: r["reason"] for r in rows}
    # a validated name keeps its backing
    assert "breadth_probe" in reasons["MSFT"]
    # a statement-only name is admitted, and says so
    assert reasons["CAMT"] == "statements_only_no_validation"
    # the three provenances stay separable
    assert len({v for v in reasons.values()}) == 3
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `uv run pytest tests/scripts/test_seed_fundamental_universe.py -v`
Expected: FAIL — `KeyError: 'CAMT'`

- [ ] **Step 3: Add the statement-bearing source to the seeder**

```python
def statement_only_tickers(conn, already: set[str]) -> list[str]:
    """Names with ingested statements that no other source admitted.

    The breadth gate gates on LAKE PRICE DEPTH, which statement ingest never
    touches. These names are ingested and rankable; they are NOT validated, and
    the reason column is what keeps that distinction alive.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT ticker FROM uw_scan.fundamental_statement_obs ORDER BY 1"
        )
        return [r[0] for r in cur.fetchall() if r[0] not in already]
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/scripts/test_seed_fundamental_universe.py -v`
Expected: PASS

- [ ] **Step 5: Run the seeder for real and record the deltas**

```bash
uv run python scripts/seed_fundamental_universe.py --dry-run
uv run python scripts/seed_fundamental_universe.py
```
Expected: `ranked` 257 → ~401. Capture the before/after counts as evidence.

- [ ] **Step 6: Run the refresh and measure what the widening actually bought**

```bash
uv run python -c "
from uw_scan.worker.jobs.fundamental_refresh import fundamental_refresh
..."   # or the scheduler's registered job path
```

Record **both** numbers separately — scores gained and bands gained. Per the revised D5 the
expectation is ~+144 scores and **up to +132 bands** (132 names clear the 12-quarter price gate on
the mini; 143 clear it on statements). 132 is a ceiling, not a forecast: the method still refuses on
non-positive EV, a non-positive numerator, and a stale filing, and this cohort is more exposed to
those than the universe was. **The realised count measured here is the answer** — record it, and if
it lands far below 132, the gap is the refusal rate on this cohort and belongs in D5.

- [ ] **Step 7: Commit**

```bash
git add scripts/seed_fundamental_universe.py tests/scripts/test_seed_fundamental_universe.py
git commit -m "feat(fundamentals): admit statement-bearing names to the ranked tier"
```

### Task 2: Schedule the statement ingest

**Files:**
- Modify: `src/uw_scan/worker/scheduler.py`
- Modify: `src/uw_scan/config.py`
- Test: `tests/worker/test_scheduler_registration.py`

**Interfaces:**
- Consumes: `worker.jobs.fundamental_ingest.fundamental_ingest` (already exists; the backfill
  script is described in its own docstring as the entry point *"until the scheduler wires it"*)
- Produces: a registered job id `fundamental_ingest`

`fundamental_refresh` recomputes derived layers nightly at zero external cost, but its docstring
states plainly that it does **not** ingest statements — the backfill script is the only path
pulling new filings, and it is manual. So the nightly job faithfully recomputes over a panel
that stops advancing the moment nobody runs the backfill by hand. This is the same failure shape
already on record as `fundamentals_refresh` never committing a row: healthy-looking and stale.

**Cadence: monthly, not daily.** Statements are quarterly, but filings arrive spread across the
calendar, so a monthly run catches each name within weeks of its filing. Cost is 4 UW calls per
ticker — ~1,600 calls at the widened 401 against a 120k/day budget.

- [ ] **Step 1: Write the failing test**

```python
def test_fundamental_ingest_is_registered(scheduler_for_role_uw0):
    ids = {j.id for j in scheduler_for_role_uw0.get_jobs()}
    assert "fundamental_ingest" in ids
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `uv run pytest tests/worker/test_scheduler_registration.py -v`
Expected: FAIL — `fundamental_ingest` not in the registered set

- [ ] **Step 3: Add the config knobs**

```python
fundamental_ingest_enabled: bool = True
fundamental_ingest_cron: str = "40 3 2 * *"   # 03:40 ET, 2nd of each month
```

Wire both through `from_env()` alongside the neighbouring `fundamental_refresh_*` entries.
**Do not add a bare `Settings()` call anywhere** — only `from_env()` loads config, and a bare
constructor is env-blind (this shipped dead alerts to production once already).

- [ ] **Step 4: Register the job on the `uw-0` role**

It spends UW budget, so it belongs on a UW role — not the massive-0 role that carries
`fundamental_refresh`.

- [ ] **Step 5: Run the test to verify it passes, then the full unit job**

Run: `uv run pytest tests/worker/ -v && uv run ruff check src scripts`
Expected: PASS

- [ ] **Step 6: Smoke the real worker path**

Restart the local stack (APScheduler does not hot-reload), let the job fire once with a
`--tickers` scope, and confirm a new `fundamental_statement_obs` row lands with a fresh
`observed_at`. Record the row count before and after.

- [ ] **Step 7: CHANGELOG and commit**

```bash
git add src/uw_scan/worker/scheduler.py src/uw_scan/config.py tests/worker/test_scheduler_registration.py CHANGELOG.md
git commit -m "feat(fundamentals): schedule the monthly statement ingest"
```

---

## PR 2 — ~~Verify the one signal that pays is actually accumulating~~ — RESOLVED 2026-08-18

**It is accumulating. The check this section specified could never have said so.**

`sales_to_ev` own-history is the only validated signal in this lane: IC **+0.0744 (t 5.77)**,
surviving the holding-reversal control (+0.0826, t 7.28), hit rate 0.683, holding at +0.0604
(t 5.45) on the trailing-20q window non-stationarity forces. What was unverified was whether the
band **accumulates in production**.

### The measurement

| | |
|---|---|
| code reached the mini | v0.12.0, 2026-08-16 (PR #331 merged 08-12; `:latest` floats only on release tags) |
| scheduled opportunities since | 2 — Sun 08-16 and Mon 08-17, cron `20 18 * * 0-4` |
| runs that wrote | **2 of 2** — 254 rows then 257 rows |
| last write | **2026-08-17 18:20 EDT**, its exact slot |
| `max(as_of)` | 2026-08-14, equal to the lake's own last close |

`valuation_anchors` carries `computed_at`. Grouping by it is what separates "the job is dead"
from "the job is healthy and `as_of` means something other than you thought".

### Why the original criterion was unsatisfiable

This section specified: *"Healthy: `count(DISTINCT as_of)` grows by one per weekday, `max(as_of)`
is yesterday or today."* That was taken from `fundamental_anchors.py`, whose docstring claimed
`as_of` **is the compute date**. The code has always set `as_of = spot_date` — the last bar in the
ticker's price series. The docstring was wrong, and this plan copied it into a gate.

The consequences were not cosmetic:

- **`max(as_of)` can never be today.** The lake is EOD and livewire lands a session's close around
  midnight New York, hours after the 18:20 ET run. A healthy Monday-evening run writes Friday.
- **Old `as_of` values are correct, not corrupt.** A ticker whose series ends in 2022 gets 2022.
  The 08-16 run wrote `as_of` spanning 2022-05-31…2026-05-29 because the lake was still catching
  up from the outage; by the 08-17 run every name had advanced to 2026-08-14.
- **The gate fires on healthy systems.** This plan called it "the highest priority item, ahead of
  everything else". Anyone executing it would have stopped here and debugged a working job.

The docstring is corrected in this PR. Keying on the clock instead would be actively wrong: a
stale lake would mint one row per calendar day carrying an identical spot, asserting price
observations on days when none existed.

### The criterion that does work

- **liveness** — `max(computed_at)` is within one scheduled slot.
- **correctness** — `max(as_of)` equals the lake's own last close, not the wall clock.
- **accrual** — `count(DISTINCT computed_at::date)` grows once per scheduled run.

```sql
SELECT date(computed_at) AS run, count(*), count(DISTINCT ticker), max(as_of)
  FROM uw_scan.valuation_anchors GROUP BY 1 ORDER BY 1 DESC LIMIT 10;
```

### Still open

Step 3 of the original section — confirm the band renders against a real ticker on the mini and
that its spot percentile moves between sessions — is **not** answered by the query above and is
not attempted here. It needs two consecutive lake-fresh sessions, which the outage backfill has
only just restored.

---

## PR 3 — Concentration capture and card

**Branch:** `feat/fundamental-concentration-ledger`

Justified by D4 (accrual optionality), scoped by D2 (descriptive only), and constrained by D3
(no edge claim anywhere in code, copy, or CHANGELOG).

### Task 1: PIT observation table

**Files:**
- Create: `src/uw_scan/storage/migrations/122_revenue_breakdown_obs.sql`
- Modify: `src/uw_scan/reports/data_gap_healer.py`
- Test: `tests/storage/test_migrations.py`

Per spec A10, statements/segments/filings are **immutable point-in-time observations** with
canonical views derived on top. Store the **raw rows as fetched** — axis, members, value,
report_date, rev_group — not the derived share. The derivation rules will change (level
selection is new and unproven); the rows will not, and re-deriving from stored rows costs
nothing while re-fetching a rolled-off quarter is impossible.

- [ ] **Step 1: Write the migration** — `IF NOT EXISTS`, PK on
      `(ticker, report_date, rev_group, axis_key, member_key, observed_at)`, plus the raw
      `value` and a `content_hash`.

  **The content hash must exclude any vendor-side `inserted_at`/`updated_at` field** or every
  refresh registers as a phantom restatement — this exact bug shipped in the tier-1 ingest.

- [ ] **Step 2: Add the `DatasetRegistryEntry`** and regenerate the dataset-policy doc. A new
      temporal table fails two CI gates without both, and both belong in this PR.

- [ ] **Step 3: Verify idempotence** — `bash scripts/migrate.sh` twice; second run is a no-op.

- [ ] **Step 4: Commit**

### Task 2: The derivation module

**Files:**
- Create: `src/uw_scan/fundamentals/concentration.py` (~250 lines)
- Test: `tests/fundamentals/test_concentration.py`

**Interfaces:**
- Produces: `shares_for_period(rows) -> dict`, `is_annual_row(total, ticker_median) -> bool`

Port the verified logic from `scripts/research/fundamental_concentration_axis_probe.py` — do not
re-derive it. The four rules, each of which a failure bucket in the original probe traces to:

1. The denominator is a property of the **period**, taken from the untagged consolidated row
   wherever it appears — never scoped to `rev_group`.
2. Group by the **XBRL axis**, never by `rev_group`.
3. `srt:ConsolidationItemsAxis` is a **scope tag**; strip it, keep the row.
4. One axis can carry several nesting levels; recover the reported level by finding the subset
   of members summing to the period total and taking the **coarsest**. Refuse a tie.

Prefer `us-gaap:StatementBusinessSegmentsAxis` over `srt:ProductOrServiceAxis` when both
reconcile — this is what resolves AVGO's known 76%-vs-68% ambiguity to the right answer.

- [ ] **Step 1: Write tests from the two hand-verified filers** — frozen real rows, as-of dated,
      no network at runtime, no placeholder tickers.

```python
def test_nvda_segment_prefers_asc280_axis(nvda_2026_04_26_rows):
    out = shares_for_period(nvda_2026_04_26_rows)
    assert out["axes"]["segment"]["axis"] == "us-gaap:StatementBusinessSegmentsAxis"
    assert out["axes"]["segment"]["top_share"] == pytest.approx(0.9134, abs=1e-4)
    assert out["axes"]["geography"]["top_member"] == "country:US"
    assert out["axes"]["geography"]["top_share"] == pytest.approx(0.7813, abs=1e-4)

def test_avgo_ambiguous_axes_resolve_to_reportable_segments(avgo_rows):
    assert shares_for_period(avgo_rows)["axes"]["segment"]["top_share"] == pytest.approx(0.6765, abs=1e-4)

def test_single_member_partition_is_refused(one_member_rows):
    """A lone member equal to the total makes the share 100% by construction."""
    assert "segment" not in shares_for_period(one_member_rows)["axes"]
```

- [ ] **Step 2: Run to confirm they fail, then port the module, then confirm they pass**

- [ ] **Step 3: Implement annual-row detection**

Per D3, 89/184 segment and 52/128 geography tickers mix an annual total into the quarterly
series, and the resulting share error is p90 **17.5pp** against a median quarterly move of
1.20pp. A total exceeding **2.5× the ticker's own median** separates them cleanly.

Store the flag on the row; **drop annual periods from the rendered trend**. Do not silently
delete them — a later reader needs to see they existed.

- [ ] **Step 4: Gate the subset path behind a flag, defaulting OFF**

14% of resolutions come from the subset search rather than the full set reconciling. NVDA and
AVGO were hand-verified; the rest were not, and a wrong-level partition produces a *plausible*
share — the failure mode this lane already has a rule about. Default to refusing subsets
(costing ~14% of coverage) until a hand-audit sample justifies flipping it.

- [ ] **Step 5: Run the full unit job and commit**

### Task 3: Quarterly capture job

**Files:**
- Create: `src/uw_scan/worker/jobs/fundamental_concentration_capture.py`
- Create: `src/uw_scan/storage/fundamental_concentration.py`
- Modify: `src/uw_scan/worker/scheduler.py`, `src/uw_scan/config.py`

- [ ] **Step 1:** Job fetches `rev_breakdown` for every universe ticker and writes raw rows.
      One ticker's failure never costs the others theirs — count and skip, never raise.
- [ ] **Step 2:** Register monthly on `uw-0`, gated `FUNDAMENTAL_CONCENTRATION_CAPTURE_ENABLED`.
      ~401 calls/run. Monthly rather than quarterly so a rolling window cannot outrun us
      between runs.
- [ ] **Step 3:** Self-gate on an empty universe, matching the research-capture jobs' pattern.
- [ ] **Step 4: Smoke the real worker path** — enqueue → worker claims → rows land → count them.
- [ ] **Step 5:** Commit.

### Task 4: Card block and the spec correction

**Files:**
- Modify: `src/uw_scan/api/routers/fundamental.py`
- Create: `web/components/stock/panels/FundamentalConcentration.tsx`
- Modify: `web/components/stock/tabs/FundamentalsTab.tsx`
- Modify: `docs/superpowers/specs/2026-08-10-fundamental-pm-agent-design.md`

- [ ] **Step 1:** Read-only endpoint returning latest share, member label, axis, and the
      annual-filtered trend. Regenerate types: `cd web && npm run gen:types`.
- [ ] **Step 2:** Render the **raw member string**, not a prettified country name — filers mix
      `country:US` with custom members like `nvda:ChinaIncludingHongKongMember` and continent
      aggregates. The share is defensible; a beautified label would not be.
- [ ] **Step 3:** Absent renders **`na`, never 0** (spec §964 — a zero reads as "no
      concentration risk", which is a fabricated fact).
- [ ] **Step 4:** Label the block as descriptive. No ranking, no score, no percentile against
      other names, and **no composite contribution**.
- [ ] **Step 5: Correct spec §896** — `concentration_risk` is not `✅ UW rev_breakdown, 24/25`.
      Replace with the measured rates, and withdraw the 0.10 composite weight per D2.
- [ ] **Step 6:** Vitest for the `na` path and the annual-drop path. Playwright screenshot to
      `output/playwright/`. Remember JSX whitespace differs between esbuild and SWC — verify in
      a browser, not only vitest.
- [ ] **Step 7:** CHANGELOG and commit.

---

## Deferred, with reasons

| Item | Why not now |
|---|---|
| Returns backtest on concentration | D3 — the contamination is ~2× the signal's median step and the panel is 8 quarters. The test cannot reach a conclusion. |
| Concentration → earnings vol test | The right test, wrong time. `option_surface_grid_daily` spans ~2–3 earnings cycles. Revisit in ~4 quarters. |
| Rebuilding the composite | It orders names and does not pay. More inputs will not change that. |
| Chain / cluster work | Closed twice, both nulls. |
| Alert pipeline v1 | D6 — deprioritised by user direction; recorded as a master-plan deviation. |
| Lake backfill for the price-less names | Belongs to market-warehouse, not argon. The D5 re-measurement shrank this from 115 names to **3** (`CFLT`, `CYBR`, `PSTG` are absent from the mini lake entirely) plus 9 more that have a file but under 12 quarters of history. Worth reporting upstream to livewire; not argon work. |

## Open questions to resolve during execution

1. ~~**Does the mini's lake mirror hold more than the MacBook's?**~~ **Answered 2026-08-18: yes,
   decisively** — 14,689 equity symbols against 653, and 132 of the 144 clear the band's depth gate
   rather than 29. D5 is revised above; `docs/research/2026-08-18-fundamental-lake-depth/`. This was
   listed as a PR-1 execution step, but it gates whether PR-1 is worth doing at all, so it was run
   first. **What remains open is the refusal rate on this cohort**, which only PR-1's ingest answers.
2. **Does UW's `rev_breakdown` window roll?** Unanswerable from one snapshot. PR-3's stored
   snapshots answer it within two runs: if the oldest period advances, it rolls, and D4's
   urgency was real.
3. ~~**Is `valuation_anchors` accruing on the mini?**~~ **Answered 2026-08-18: yes** — 2 of 2
   scheduled runs since the v0.12.0 deploy wrote rows, the last at its exact 18:20 ET slot. The
   check this plan specified could not have said so; see the rewritten PR 2. What remains open is
   Step 3, whether the rendered band's spot percentile actually moves between sessions.
