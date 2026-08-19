# Macro MC2 Inflation and Rates State Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** build point-in-time inflation and policy/rates states from free official evidence, replace
false precision with state/direction/velocity/confidence, and adapt the existing rates surface without
deleting its history.

**Architecture:** inflation and rates are pure domain engines over MC0 observations. Inflation owns
realized inflation, breadth/stickiness, expectations, and momentum; rates owns policy paths, curve,
decomposition, supply, positioning, and plumbing. Shared inputs are referenced once and causal roles
are explicit. Legacy `RatesScorecard` remains available during dual-read but is not the new state
contract.

**Tech Stack:** existing FRED/Cleveland Fed/FOMC/CFTC/Treasury clients, new official BLS/BEA adapters,
Postgres, Pydantic v2, FastAPI, Vitest/Playwright.

---

## Preconditions and PR boundary

- MC0 and MC1 gates pass.
- Recheck migration numbering; this plan reserves `116_macro_domain_states.sql`.
- Source scope is intentionally bounded: BLS CPI, BEA PCE, FRED/ALFRED-compatible market series,
  Cleveland Fed decomposition, FOMC/SEP, CFTC TFF, Treasury/FiscalData. Survey breadth can land only
  after its own free-source fixture/probe.
- Do not fit a forecasting model or promote duration BUY/SELL in this PR.

### Task 1: Preregister state definitions and golden scenarios

**Files:**
- Create: `docs/superpowers/specs/2026-08-12-inflation-rates-state-design.md`
- Create: `tests/fixtures/macro/inflation_rates_golden.json`

Define load-bearing inputs, units, release lags, horizons, missingness, contradiction rules, and
state labels before implementation. Include at least:

1. disinflation with sticky services;
2. broad reacceleration;
3. dovish SEP but hawkish market pricing;
4. rising nominal yield driven by real yields;
5. supply pressure with neutral macro inputs;
6. stale or revised CPI/PCE.

For every scenario specify expected state, direction, velocity, confidence reasons, and evidence
roles. Curves/slopes may describe shape but cannot stand in for term premium.

### Task 2: Add official BLS and BEA fixtures and failing parser tests

**Files:**
- Create: `src/uw_scan/sources/bls.py`
- Create: `src/uw_scan/sources/bea.py`
- Create: `tests/unit/sources/test_bls.py`
- Create: `tests/unit/sources/test_bea.py`
- Create: `tests/fixtures/macro/bls_cpi_release.json`
- Create: `tests/fixtures/macro/bea_pce_release.json`

**Steps:**

1. Write tests first for release date, observation period, units, seasonal-adjustment identity,
   headline/core components, and missing/changed schemas.
2. Implement thin official-source clients with injected request-audit hooks.
3. Normalize publisher rows into MC0 observations; do not calculate YoY in source modules.
4. Test zero rows and HTTP errors remain distinct.
5. Run tests. Expected: PASS after minimal implementation.

### Task 3: Implement pure inflation state

**Files:**
- Create: `src/uw_scan/macro/contracts.py`
- Create: `src/uw_scan/macro/inflation.py`
- Create: `tests/unit/macro/test_inflation_state.py`

**Required output:** `MacroDomainState(domain="inflation", state, direction, velocity,
confidence, confidence_reasons, contradictions, factors, evidence_refs, engine_version,
inputs_hash, as_of)`.

**Steps:**

1. Write failing golden-scenario tests.
2. Compute publisher-defined MoM/YoY/annualized changes only from observations available by `as_of`.
3. Separate realized headline/core, breadth/stickiness, survey/model expectations, and market
   compensation. Do not call breakevens pure expectations.
4. Make thresholds/transformations versioned parameters, not module constants hidden from hashes.
5. Confidence is a deterministic function of completeness, freshness, source quality, revisions,
   and contradictions; it is not the absolute value of the signal.
6. Run unit tests and verify every golden scenario.

### Task 4: Implement pure policy/rates state and remove proxy ambiguity

**Files:**
- Create: `src/uw_scan/macro/rates.py`
- Modify: `src/uw_scan/rates/calculations.py`
- Modify: `src/uw_scan/rates/scorecard.py`
- Create: `tests/unit/macro/test_rates_state.py`
- Modify: `tests/unit/rates/test_scorecard.py`

**Steps:**

1. Build policy stance from the four MC1 paths without averaging them.
2. Build curve/decomposition state from nominal, real, inflation compensation, and the existing
   Cleveland model's explicit components.
3. Keep supply, positioning, and plumbing as separate factors with their own freshness.
4. Rename or remove any UI/API field that describes slope as term premium; preserve compatibility
   with a deprecation alias if required.
5. Change legacy scorecard behavior so incomplete groups cannot produce a confident stance:
   `duration_stance` remains neutral/unknown with explicit coverage when load-bearing groups are
   missing.
6. Test threshold edges, missing groups, stale inputs, path disagreement, and decompositions whose
   components do not add within tolerance.

### Task 5: Persist versioned domain states and evidence associations

**Files:**
- Create: `src/uw_scan/storage/migrations/116_macro_domain_states.sql`
- Modify: `src/uw_scan/storage/macro_context.py`
- Modify: `src/uw_scan/reports/data_gap_healer.py`
- Modify: `docs/runbooks/data-gap-dataset-policy.md`
- Modify: `tests/integration/storage/test_macro_context_repository.py`

**Required tables:**

```text
macro_domain_states
  state_id, domain, as_of, computed_at, engine_version, inputs_hash
  state, direction, velocity_jsonb, confidence, confidence_reasons_jsonb
  contradictions_jsonb, factors_jsonb, status
  UNIQUE (domain, as_of, engine_version, inputs_hash)

macro_domain_state_evidence
  state_id FK, obs_id FK, causal_role, ordinal
  PRIMARY KEY (state_id, obs_id, causal_role)
```

Add repository methods for insert/fetch/replay, immutable method identity, typed evidence FKs, and
dataset-registry entries. Run migrations twice and the full registry-policy gate.

### Task 6: Add worker jobs and dual-read rates API

**Files:**
- Create: `src/uw_scan/worker/jobs/macro_state_jobs.py`
- Modify: `src/uw_scan/worker/scheduler.py`
- Modify: `src/uw_scan/api/routers/macro.py`
- Modify: `src/uw_scan/api/routers/rates.py`
- Modify: `src/uw_scan/models/macro.py`
- Create: `tests/integration/worker/test_macro_state_jobs.py`
- Create: `tests/integration/api/test_macro_state_router.py`
- Modify: `tests/integration/api/test_rates_router.py`

**Steps:**

1. Ingest official releases independently from state computation; state jobs read persisted evidence.
2. Add `GET /api/macro/inflation` and `GET /api/macro/rates` with `as_of` replay.
3. Add a feature-flagged state/confidence block to `/api/rates/snapshot`; keep the legacy payload
   until web parity is measured.
4. Test provider-down computation from persisted evidence, idempotent recompute, stale labeling, and
   exact evidence references.

### Task 7: Adapt the rates UI to evidence-first presentation

**Files:**
- Modify: `web/components/rates/RatesDesk.tsx`
- Modify: `web/components/rates/RatesScorecard.tsx`
- Create: `web/components/rates/PolicyPathComparison.tsx`
- Modify: `web/tests/unit/rates/RatesScorecard.test.tsx`
- Modify: `web/tests/unit/rates/RatesDesk.test.tsx`
- Create: `web/tests/e2e/macro-rates-state.spec.ts`

**Steps:**

1. Lead with state, direction, velocity, confidence reasons, and contradictions.
2. Render actual/SEP/dealer/market paths in separate lanes with source and release date.
3. Demote legacy composite/stance behind an “experimental legacy” label while dual-read remains.
4. Render missing/stale/mock-rejected states without fabricated zeros.
5. Browser-test replay, partial paths, stale data, and no-score behavior.

### Task 8: Verification and conditional checkpoint

Run targeted source, macro, storage, worker, API, web-unit, type-generation, and Playwright suites;
run migrations twice; run `git diff --check`. Then run the real source → worker → DB → API →
browser smoke after restarting the worker stack.

If and only if explicitly authorized, checkpoint with a scoped `feat(macro): add inflation and rates
state engines` commit.

## MC2 exit criteria

- inflation and rates states replay under `available_at <= as_of`;
- exact observation FKs reconstruct every state;
- incomplete data abstains or degrades explicitly;
- policy paths never merge;
- slope is not presented as term premium;
- legacy stance is visibly experimental and cannot become confident from missing groups;
- real worker/database/API/browser path passes.

## Recorded deviations

Deviations from the plan as written, with the reason each was taken.

1. **Task 5 migration number: `116` → `123`.** The plan reserved 116; 116..122 were claimed by
   intervening work (`116_macro_source_status` through `122_revenue_breakdown_obs`) before this task
   started. The reservation moved rather than the file being renumbered into a duplicate prefix.

2. **Task 5 landed in new modules instead of extending `macro_context.py`.** That module was already
   604 lines — past the repo's 500-line target — and domain states are a different seam from artifact
   and observation ingestion, so the work went to `storage/macro_domain_state.py` (mixin wired into
   `Repository` assembly) and `tests/integration/storage/test_macro_domain_state_repository.py`. No
   method was added to `macro_context.py`.

3. **Task 5 columns beyond the plan's list: `notes_jsonb`, `quarantined_at`, `quarantine_reason`,
   and a one-way `status` transition.** The plan named `status` without saying what writes it. Left
   as a single-valued column it records nothing, so it now carries the only retraction a
   write-guarded table can express: `published → quarantined`, enforced by trigger, which withdraws
   a state computed by an engine later found wrong without editing what that state said.
   `notes_jsonb` exists because `MacroDomainState.notes` would otherwise be dropped on persist.

4. **Task 6 added two files the plan does not list: `worker/jobs/macro_series_ingest.py`
   and `macro/evidence_store.py`.** Step 1 requires that official releases be ingested
   independently of state computation and that state jobs read persisted evidence. The
   policy releases already had an ingest (MC1), but nothing wrote the FRED series the
   inflation engine reads — `sources/fred_macro.py` had parser tests and no consumer. Without
   the ingest the state job would abstain forever in production, so the task was not
   deliverable from the listed files alone. `evidence_store.py` is the read half: turning
   stored rows back into `DomainObservation` needs the causal role and publisher transform,
   neither of which is a column, and both jobs plus any future domain need the same mapping.

5. **Migration `124` was not planned; it splits an availability bound that migration 115
   states as universal.** 115 refuses any observation that became available before the
   artifact carrying it — correct for a release, and backwards for a vintage record, whose
   entire product is reporting today when a value was published in the past. Enforced in a
   trigger, so it could not be worked around in application code. `vintage_bearing` on the
   artifact selects which bound applies; the forward direction (a vintage may never postdate
   the fetch reporting it) is enforced for both. The replacement trigger body was rebuilt
   verbatim from 115 with only that block substituted, after a hand-written version silently
   altered the content-hash formula.

6. **`macro/rates.py` was changed during Task 6: the state now cites its policy releases.**
   Task 4 emitted `evidence_refs` for market observations only, so a rates state whose
   `state` field came from the FOMC target range named every input except that one — and a
   rates state with no market series had no citable evidence at all and could not be stored.
   `inputs_hash` is unchanged: the paths were already identified inside `parameters`.

7. **The API returns stored states and 404s rather than computing on read.** The plan says
   "with `as_of` replay" without saying which. Recomputing a past instant with today's
   engine reports what we would now say about then, which is not what we said; that makes
   the record regenerable to taste. `fetch_macro_domain_state_as_of` gained
   `strictly_before` for the same reason: a recompute must select its prior state
   deterministically, or two runs over identical evidence produce different confidence and
   the identity guard (correctly) refuses the second.

8. **Task 7 touched three files the plan does not list:
   `web/components/rates/sections/StateSection.tsx` (new), `web/lib/api.ts` and
   `web/app/rates/page.tsx`.** Step 2 requires the four policy paths on the page, and
   they do not live in the rates snapshot — they come from `GET /api/macro/policy`,
   computed by a different job on a different clock. Nothing in the listed file set
   could feed `PolicyPathComparison`, so the task was not deliverable from them alone;
   the page now settles the two fetches independently, because a policy-ingest outage
   must not blank a curve that is still a fact. `StateSection` went to `sections/`
   rather than inline: that directory already holds the page's composed blocks
   (Decomposition, Policy, Supply, Positioning) and `RatesDesk.tsx` was already 461
   lines.

9. **The scorecard's client-side composite was deleted rather than repaired.** Step 4
   asks for no fabricated zeros; the fabrication was a *second* implementation. The
   component renormalised the weights itself and fell back to `0` on a zero
   denominator, which `stance()` then rendered as "NEUTRAL duration". Patching the
   fallback would have left two independent answers on one card — a server that
   refuses a stance beside a client that takes one. The server already owns the
   composite and the coverage floor, so the client now prints what it decided,
   including the refusal.

10. **Replay is browser-tested through the API, not through a `?as_of=` on `/rates`.**
    Step 5 says "browser-test replay". `/api/rates/snapshot` has no `as_of` parameter,
    so a replay control on the page would replay the state and policy blocks while the
    curve, decomposition, supply and positioning stayed live — a half-replayed page
    that reads as a fully replayed one, which is the failure this milestone exists to
    prevent. `tests/e2e/macro-rates-state.spec.ts` exercises replay against the same
    origin the page uses (through the Next `/api/*` rewrite) and asserts the page's
    rendering invariants separately.

11. **The web fixture's policy paths are parser output over the committed official
    fixtures, not hand-written numbers.** `web/tests/unit/rates/fixture.ts` carries the
    real FOMC 2026-06-17 statement (Hold, 3.50–3.75%, vote 12-0 with **no roster
    printed**), the real SEP 2026-06 federal-funds projections (2026 median 3.8,
    central tendency 3.6–4.1, 18 dots) and the real NY Fed SME June 2026 dealer path
    (n=26). The market-implied lane is deliberately absent — Frenzy is optional,
    default-off, and this repo commits no fixture for it — which also gives step 5 its
    partial-path case. The 12-0-with-no-roster statement is the reason
    `voter_names_stated` exists, and it is now a rendering test rather than a comment.

12. **Task 8's checkpoint commit is scoped to the UI, not to "the state engines".** The
    plan named one commit, `feat(macro): add inflation and rates state engines`, on the
    assumption the milestone landed as a single checkpoint. The engines, persistence and
    replay API had already landed in five earlier commits on this branch, so a commit
    claiming to add them would misdescribe its own diff. The checkpoint carries what
    Task 7 actually produced and is named for it.

## Task 8 verification

Run 2026-08-19 against live publishers and a real browser.

| Gate | Result |
|---|---|
| Source parsers (FOMC / SEP / SME / calendar / census / discovery / treasury) | 130 passed |
| Macro + rates unit (engines, models, contract, worker, scripts) | 168 passed |
| Integration — storage, worker, API | 137 passed |
| OpenAPI snapshot / contract | 24 passed |
| Web unit (vitest) | 777 passed across 116 files |
| Playwright `macro-rates-state.spec.ts` | 8 passed, 0 skipped |
| Playwright `golden-path` regression | 1 passed |
| Migrations applied twice | clean both passes |
| `npm run gen:types` | regenerates byte-identical |
| `git diff --check`, ruff, `check_no_yahoo.py`, tsc, eslint | clean |

Real path, no fixtures: FOMC 5/5 releases parsed, SEP 2/2, SME 1/1 (16 raw artifacts),
FRED 6,726 observations, both domain states computed and stored, rendered at `/rates`.
The live 2026-07-29 statement prints a 9-3 tally and names nobody, so the
`voter_names_stated=false` branch is exercised by production data, not only by fixtures.

### Defect found by this run, RESOLVED in Task 9: FRED refuses every daily series

`macro_series_ingest.py` requests the unbounded vintage window
(`ALL_VINTAGES_START` .. `ALL_VINTAGES_END`) and documents it as "not a tunable knob",
because a narrower window is clamped onto the returned rows and destroys the
point-in-time field. That holds for monthly series and fails for daily ones: FRED caps a
`file_type=json` request at **2000 vintage dates**, and a daily series mints one per
business day.

    There are 5090 vintage dates in the specified real-time period: 1776-07-04 to
    9999-12-31. This exceeds the maximum number of vintage dates allowed for this
    file type (2000).

All 8 monthly inflation series ingest; all 3 daily series (`DGS10`, `DFII10`, `T10YIE`)
fail. `RATES_EVIDENCE` is entirely daily, so `policy_rates` permanently reports
`market_factors_absent` for curve, decomposition_component, supply, positioning and
plumbing. The state still computes and names the absence, so no exit criterion is
violated — the rates domain simply cannot see the market layer.

Measured boundary on `DGS10` with `observation_start == realtime_start`:

| `realtime_start` | vintage dates | result |
|---|---|---|
| 1776-07-04 | 5090 | 400 |
| 2015-01-01 | 2871 | 400 |
| 2019-01-01 | 1993 | 200 |
| 2023-01-01 | 946 | 200 |

Bounding the window does **not** clamp the vintages: asking from 2019-01-01 returns the
2019-01-01 observation with its true `realtime_start` of 2019-01-03, not the window
edge. So a bounded daily window is safe for replay as long as the bound predates the
first observation's publication day. The tension a fix must resolve: the cap is on
vintage *count*, which grows ~248/year for a daily series, so any fixed start eventually
crosses 2000 again, while a rolling start changes the payload bytes every run and mints
a fresh artifact for an unchanged history — the churn the fixed
`DEFAULT_OBSERVATION_START` exists to prevent. Deferred rather than decided
unilaterally: it trades off two properties this milestone treats as load-bearing.

*(One number above was corrected in Task 9: "2023-01-01 buys until roughly 2027" was
wrong. The cap bounds window WIDTH, so a start date buys `2000 / 248 ≈ 8.06` years
regardless of which start it is — 2023-01-01 runs to roughly 2031, not 2027.)*

## Task 9: FRED daily-series window, and the two path plots

Authorized directly rather than planned: fix the daily-series defect, then add two
plotted blocks below Summary.

### The window

`DAILY_VINTAGE_START = 2021-01-01`, applied by a new `request_window(series_id,
observation_start)` that splits on the contract's own `frequency`. Monthly series keep
the unbounded window byte-for-byte; daily series get `observation_start ==
realtime_start == DAILY_VINTAGE_START`.

**Why the equality is the correctness condition, not a coincidence.** The clamping the
module docstring warns about happens when the requested window *excludes* an
observation's real vintage. An observation cannot be published before the day it
describes, so if the earliest observation starts where the earliest vintage starts,
nothing returned can have a true vintage outside the window and nothing can be clamped.
A bounded `realtime_start` alone would not be safe; the pair is.

Measured against the live API 2026-08-19, `observation_start == realtime_start`:

| start | rows | distinct vintages | first obs | its true vintage |
|---|---|---|---|---|
| 2015-01-01 | — | — | HTTP 400 | — |
| 2019-01-01 | 1993 | 1891 | 2019-01-01 | 2019-01-03 |
| 2020-01-01 | 1732 | 1644 | 2020-01-01 | 2020-01-03 |
| 2021-01-01 | 1469 | 1395 | 2021-01-01 | 2021-01-05 |

The true vintage is never the window edge, which is the property the fix rests on.
Growth is 496 vintages per 2 years = ~248/year, so the ceiling is a window **width** of
~8.06 years, not a particular start date.

**Why 2021-01-01.** The start is not a compute window — the engines read 18 months
(inflation) and 45 days (rates) — it is the **replay floor**. 2021-01-01 keeps the
entire 2021–23 inflation surge and hiking cycle replayable, the regime a rates state is
most worth replaying against, while leaving ~2.4 years of headroom. A later start buys
time by deleting exactly that history.

**Why the comment is not the deliverable.** A dated constant with an 8-year life rots
silently. `test_daily_vintage_start_has_not_expired` fails while a year of headroom
remains, so the renewal arrives as a red build on a knowable date rather than as a dead
feed. The failure message names the cost of renewing (it raises the replay floor).

Real-path result, live publishers against `option_wizard_local`:

| | before | after |
|---|---|---|
| series ingested | 8/11 | **11/11** |
| observations created | 0 | 4223 |
| observations unchanged | 6726 | 6726 |
| `policy_rates` `market_factors_absent` | 5 | **3** |

`unchanged=6726` is the monthly-series regression check: identical to the prior run's
total, so no monthly payload changed and no artifact churned. The remaining 3 absent
factors (supply, positioning, plumbing) have no FRED series in `RATES_EVIDENCE` at all
and are a separate gap, not this defect.

### The two plots

`SepDotPlot` and `DealerPathChart`, as sections `#sep-plot` and `#dealer-plot` directly
below `#summary`. Both read the same `/api/macro/policy` slots the lanes read; the lanes
stay as the provenance surface.

Three rules the plots inherit rather than restate:

1. **Separate blocks, separate axes.** A shared frame would draw the comparison the
   desk refuses to make numerically. Asserted structurally (one `<svg>` per section),
   not by grepping prose.
2. **Anonymity survives the format change.** Dot position within a horizon is spacing,
   never identity, and every per-dot `<title>` says so — the caption alone would leave
   the tooltips attributable.
3. **An empty chart is a claim.** A bare axis reads as a flat path, so an unavailable,
   unreadable or non-publisher release renders the sentence instead. `plottable()` in
   `policyPath.ts` is the single place that decides, shared with the lanes so a mock
   source cannot slip through one surface after being refused by the other.

Two presentation bugs found by looking at the rendered output rather than the tests:
the SEP header summed the columns to "71 dots", which reads as a participant count and
is not one (it is now the per-horizon maximum, 18); and the dealer caption ran two
sentences together without a space.
