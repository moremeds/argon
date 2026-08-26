# Macro MC3 Rates Market Layer, USD Transmission and Gold State Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** give the rates domain the market layer it already declares and cannot see, then add a
free-first USD-transmission state and adapt Gold Compass to the shared macro evidence contract so
that every gold output references all inputs it actually consumed.

**Architecture:** the rates market layer (supply, positioning, plumbing) lands once, in the shared
evidence store, and is read by whichever domain needs it. USD is a transmission domain, not a
duplicate inflation/rates score: it consumes shared upstream state IDs plus official broad-dollar,
relative-policy, funding/liquidity and positioning evidence. Gold preserves its three lenses —
structural flow, regime-gated cyclical, and valuation overlay — but emits a versioned macro domain
state with complete typed provenance.

**Tech Stack:** FRED, Treasury FiscalData, CFTC, Federal Reserve H.10, BIS SDMX/CSV, existing Gold
Compass sources and cards, MC0/MC2 storage/contracts, FastAPI and React.

---

## Why the market layer is in this plan and not a separate one

MC3 declares `funding/liquidity` and `positioning` as USD transmission factors. The rates domain
declares the same two, plus `supply`, as its own market factors. If MC3 sources them for USD while
`policy_rates` stays blind, the same publisher payload is ingested twice under two owners — the
exact double-count Task B1 is required to prohibit. The layer therefore lands once, before either
domain reads it, and this plan owns both halves.

It is also nearly built already. `MacroCausalRole` has carried `supply`, `positioning` and
`plumbing` since MC0 (`models/macro.py:59-61`), and the rates engine already enumerates all five
market roles and names the absent ones (`macro/rates.py:470-490`). The engine is waiting on
evidence, not on engineering.

## Preconditions and PR boundary

- MC0/MC1/MC2 gates pass; MC2 merged as PR #359 in v0.12.10.
- Shared real-yield, inflation-compensation, policy-path and broad-dollar ownership is fixed by MC2.
- Recheck endpoint availability before choosing any adapter and persist live-probe evidence.
- Do not add Yahoo/yfinance, a DXY `static` fallback, a gold price target, allocation, or sizing.
- Existing `/rates` and `/gold` remain usable throughout.
- One branch, milestone commits. Part A is a genuine prerequisite for Part B, so if the cumulative
  diff outgrows a single reviewable unit, surface the Part A/Part B seam as the split point and let
  the operator decide. Do not split unilaterally.

## Two rulings this plan makes, and what would overturn them

Recorded here rather than left to discover mid-task. Both are defaults; either can be overridden by
the operator before Task A3 lands.

### R1 — a backfilled observation gets `published_at = NULL`, never a derived instant

Treasury auction results and CFTC COT reports follow published release schedules, so it is tempting
to derive each historical row's publication instant by rule (`COT report_date + 3 days at 15:30
ET`). Refuse that. The rule shifts on holiday weeks, and a derived instant is indistinguishable in
the schema from an observed one.

Instead use the mechanism migration 115 already provides: `published_at` is nullable
(`115_macro_evidence.sql:95`) and `available_at` is not, under `CHECK (published_at IS NULL OR
published_at <= available_at)`. A backfilled row writes `published_at = NULL` and `available_at =`
our retrieval clock. That is conservative in the only direction that matters — it never claims we
could have known something before we fetched it.

The cost, stated plainly: deep history is not PIT-replayable before its fetch date. That is not a
limitation this choice introduces; it is the true epistemic state of a row we first saw last week.
And it is recoverable — migration 119 already implements exactly one `NULL -> value` resolution of
`published_at`, carrying `available_at` to the same instant, so a later verified publication time
can be promoted without rewriting history.

**Overturned by:** a publisher field carrying the actual release timestamp per record. Task A2
probes for one; if FiscalData or CFTC expose it, use it and record the change here.

### R2 — the policy confidence denominator does not change

My first reading of prod was that `policy_rates` reporting `confidence 1.00` beside
`market_factors_absent = 3` was overstated. Reading `macro/rates.py:486` shows the split is
deliberate and correctly drawn: the market factors "do not gate the policy state but their
sub-states are unavailable." The policy state answers what the committee did, and an absent COT
report does not make that answer less certain. `required_ids` stays the three policy paths, and
`rates.py:169` already documents why widening it would let the market shadow stand in for an absent
dealer path.

What must change is presentation, not arithmetic. Once the market layer has evidence, its
sub-states publish their own confidence, and no surface may render the policy-path confidence
adjacent to a market sub-state in a way that implies one covers the other.

**Encoded as a test, not a comment:** a test fails if any market role enters `POLICY_REQUIRED`, and
a second fails if a sub-state renders without its own confidence term.

---

# Part A — the rates market layer

### Task A1: Preregister the market-layer contract and golden scenarios

**Files:**
- Create: `docs/superpowers/archive/specs/2026-08-21-rates-market-layer-design.md`
- Create: `tests/fixtures/macro/rates_market_layer_golden.json`

Define, before any adapter is written:

- which publisher owns each of `supply`, `positioning`, `plumbing`, with units and release cadence;
- the sub-state each role produces, its direction/velocity horizons, and its own confidence terms;
- missingness, staleness and contradiction rules per role;
- R1 and R2 above, restated as contract text with their overturn conditions;
- the prohibition on any role being read from a legacy overwrite-on-conflict table.

Golden scenarios must include at least:

1. heavy auction settlement against otherwise neutral macro inputs;
2. a positioning extreme against a flat curve;
3. plumbing stress — RRP drain with falling reserve balances — under an unchanged policy state;
4. a COT week that was never published, distinguished from one that failed to parse;
5. a backfilled observation correctly refused for a replay `as_of` earlier than its fetch clock;
6. a plumbing series that is fresh while positioning has gone stale past its own cadence.

For each: expected sub-state, direction, velocity, confidence reasons and evidence roles.

### Task A2: Probe the market-layer publishers and persist the evidence

**Files:**
- Create: `scripts/research/rates_market_layer_probe.py`
- Create: `docs/research/2026-08-21-rates-market-layer-probe/README.md`
- Create: `docs/research/2026-08-21-rates-market-layer-probe/probe.json`
- Create: `docs/research/2026-08-21-rates-market-layer-probe/VERDICT.md`

**Steps:**

1. Probe the plumbing candidates on FRED — `SOFR`, `EFFR`, `RRPONTSYD`, `WRESBAL` — for existence,
   frequency, unit, vintage behaviour and history span. These are candidates, not a decided set:
   none is registered in `sources/fred_macro.py` today, which carries exactly 11 series.
2. For every daily candidate, measure the vintage count under `DAILY_VINTAGE_START = 2021-01-01`
   and confirm it clears FRED's 2000-vintage cap with headroom. A weekly series such as `WRESBAL`
   must be confirmed weekly, since `request_window()` splits on the contract's own `frequency`.
3. Probe Treasury FiscalData auctions and CFTC TFF for a per-record publication-timestamp field.
   Record the answer explicitly — it is R1's overturn condition.
4. Record zero-row, transport-error and not-published outcomes as distinct results.
5. Write the verdict: chosen series per role, rejected candidates with the reason, and whether R1
   stands.

### Task A3: Bridge supply and positioning into the evidence store

**Files:**
- Create: `src/uw_scan/macro/rates_market.py`
- Create: `src/uw_scan/worker/jobs/macro_market_layer_ingest.py`
- Create: `tests/unit/macro/test_rates_market.py`
- Create: `tests/integration/worker/test_macro_market_layer_ingest.py`
- Modify: `src/uw_scan/worker/scheduler.py`

**Steps:**

1. Write the failing tests from the Task A1 fixture first.
2. Fetch from the publishers directly through the existing `sources/treasury_supply.py` and
   `sources/cftc_tff.py` clients. **Never read `rates_treasury_auctions`, `rates_fiscal_debt_daily`
   or `rates_cftc_tff_weekly` as an evidence source.** Those tables key on `(series_id, obs_date,
   source)` and update on conflict (`052_rates_tables.sql`); a value read from them may already have
   been overwritten, and promoting it to an immutable observation would launder a mutated number
   into the evidence store. They remain legacy read models for the existing `/rates` surface.
3. Preserve artifact bytes, content hash, source URL and retrieval time per the MC0 contract before
   parsing anything.
4. Apply R1: forward-accrued rows carry the observed publication instant when the publisher gives
   one, backfilled rows carry `published_at = NULL` with `available_at` at the retrieval clock.
5. Add the ingest job behind `UW_SCAN_MACRO_MARKET_LAYER_INGEST_ENABLED`, default off until the
   probe verdict and a real run exist. Schedule on `uw-0` clear of the 18:45–19:40 ET macro block.
6. A malformed or absent release fails closed with a bounded, release-specific error. It never
   becomes zero, neutral or unchanged.

### Task A4: Register the plumbing series and extend `RATES_EVIDENCE`

**Files:**
- Modify: `src/uw_scan/sources/fred_macro.py`
- Modify: `src/uw_scan/macro/evidence_store.py`
- Modify: `tests/unit/sources/test_fred_macro.py`
- Modify: `tests/unit/macro/test_evidence_store.py`

**Steps:**

1. Add the probe-selected plumbing series to `SERIES_CONTRACT` with unit and publisher transform.
2. Extend `RATES_EVIDENCE` with the `supply`, `positioning` and `plumbing` contracts. Leave the
   `DGS10 -> curve` tagging and its docstring alone: the Cleveland reconciliation rule looks its
   legs up by series id precisely so the tagging cannot mute it, and that stays dormant until
   `CLEVELAND_MODEL_NOMINAL_10Y` has an ingest of its own.
3. Assert the monthly-series payloads are byte-identical after the change — the `unchanged=6726`
   regression check from MC2 Task 9 is the model. A new daily series must not churn a monthly one.
4. Confirm `test_daily_vintage_start_has_not_expired` still passes with the widened daily set.

### Task A5: Publish the market sub-states with their own confidence

**Files:**
- Modify: `src/uw_scan/macro/rates.py`
- Modify: `src/uw_scan/macro/rates_rules.py`
- Modify: `tests/unit/macro/test_rates_state.py`
- Modify: `tests/integration/storage/test_macro_context_repository.py`

**Steps:**

1. Emit each market role's sub-state with direction, velocity and its own confidence terms.
2. Keep `POLICY_REQUIRED` unchanged per R2 and add the test that fails if a market role enters it.
3. Keep `market_factors_absent` as an `informational` term. It should now report `0`; the term must
   survive so a future regression is visible rather than silent.
4. Add the contradiction rules the spec defines — at minimum a positioning extreme that disagrees
   with the curve's direction.
5. Capture before/after evidence from a real run: `market_factors_absent` 3 -> 0, per-sub-state
   confidence, and the observation counts by causal role.

---

# Part B — USD transmission and gold

### Task B1: Preregister USD and gold causal roles

**Files:**
- Create: `docs/superpowers/archive/specs/2026-08-12-usd-gold-state-design.md`
- Create: `tests/fixtures/macro/usd_gold_golden.json`

Define:

- upstream shared inputs versus domain-owned inputs, naming Part A's roles as upstream;
- USD transmission factors: broad effective dollar, real/relative policy, funding/liquidity,
  positioning, and risk transmission;
- Gold Lens 1 structural flows, Lens 2 regime-gated cyclical factors, and Lens 3 valuation overlay;
- contradiction, missingness, freshness, and confidence rules;
- explicit prohibition on counting real yields, inflation compensation, USD, or any Part A market
  role twice.

Golden scenarios must include policy/USD disagreement, post-2022 gold/real-yield decoupling, strong
central-bank/ETF flows with adverse cyclical inputs, and stale/missing COMEX/WGC inputs.

### Task B2: Add official USD source probes and parsers

**Files:**
- Create: `src/uw_scan/sources/fed_h10.py`
- Create: `src/uw_scan/sources/bis_eer.py`
- Create: `tests/unit/sources/test_fed_h10.py`
- Create: `tests/unit/sources/test_bis_eer.py`
- Create: `scripts/research/usd_source_probe.py`
- Create: `docs/research/2026-08-12-usd-source-probe/README.md`
- Create: `docs/research/2026-08-12-usd-source-probe/probe.json`
- Create: `docs/research/2026-08-12-usd-source-probe/VERDICT.md`

**Steps:**

1. Test/parse Federal Reserve broad-dollar/H.10 series and BIS nominal/real effective exchange-rate
   metadata with units and country/basket identity.
2. Preserve publisher release time and content hash; zero rows and transport errors remain distinct.
3. Probe historical span, revision behavior, rate limits, and anonymous access.
4. Select one official primary and one cross-check; record the rejected path if either is unstable.
5. Any client added here sets `trust_env=False`. Four rates clients inherited ambient proxy config
   and froze every native macOS run; the container was immune, so a green prod is not evidence.

### Task B3: Implement pure USD transmission state

**Files:**
- Create: `src/uw_scan/macro/usd.py`
- Create: `tests/unit/macro/test_usd_state.py`
- Modify: `src/uw_scan/models/macro.py`

**Steps:**

1. Write golden-scenario tests first.
2. Consume MC2 inflation/rates state IDs rather than recomputing their inputs, and read Part A's
   positioning and plumbing observations rather than re-ingesting them.
3. Treat broad-dollar level/momentum, relative policy, liquidity/funding, and CFTC positioning as
   separate factors; preserve contradictions.
4. Define velocity horizons in configuration and include them in `engine_version/inputs_hash`.
5. Abstain when the official broad-dollar anchor is missing; no static or third-party substitute may
   silently become primary.

### Task B4: Build complete Gold Compass evidence mapping

**Files:**
- Create: `src/uw_scan/macro/gold.py`
- Modify: `src/uw_scan/reports/gold_posture.py`
- Modify: `src/uw_scan/storage/gold.py`
- Create: `tests/unit/macro/test_gold_state.py`
- Modify: `tests/integration/reports/test_gold_posture_orchestrator.py`
- Modify: `tests/integration/e2e/test_gold_replay_acceptance.py`

**Steps:**

1. Add a failing test enumerating every consumed source: GLD/gold price, CPI, M2, T5YIFR, DFII10,
   DXY/broad dollar, GPR, central-bank reserves, ETF holdings/flows, COMEX/LBMA, CFTC COT, and UW
   options where present.
2. Replace the four-entry `inputs_used` manifest at `reports/gold_posture.py:380` — today it pins
   `DFII10`, `GLD_CLOSE`, `T5YIFR` and `CPIAUCSL` while the orchestrator consumes roughly eleven
   inputs — with typed evidence associations for all consumed rows. An optional absent input is
   recorded as an omission reason, not a fake evidence ID.
3. Preserve the three lens outputs and the post-2022 regime gate. Lens 3 remains a valuation warning,
   never a sizing input.
4. Emit a `MacroDomainState(domain="gold")` referencing the existing deterministic lens result and
   shared MC2/Part A/B3 upstream states.
5. Verify old replay dates still render and new replay reconstructs the exact evidence manifest.

### Task B5: Persist USD/gold states and cross-domain lineage

**Files:**
- Modify: `src/uw_scan/storage/macro_context.py`
- Create: the next additive migration, numbered at implementation time
- Modify: `tests/integration/storage/test_macro_context_repository.py`

**Steps:**

1. Persist USD/gold through the same `macro_domain_states` contract as inflation/rates. MC2 landed
   that table as migration `125`, not the `116` this plan originally reserved.
2. Take the migration number immediately before writing it and re-check it at merge. The prefix is a
   shared namespace with no reservation mechanism, and git merges two files with the same prefix
   without a conflict — MC2 renumbered twice for this reason.
3. Add typed state-to-state dependency associations if MC2 did not include them:
   `(downstream_state_id, upstream_state_id, causal_role)`.
4. Test the same upstream state can be referenced by USD and gold without copying observations.
5. Test a changed upstream state changes downstream `inputs_hash` and preserves the predecessor.

### Task B6: Add jobs, API, and dual-read Gold/UI integration

**Files:**
- Modify: `src/uw_scan/worker/jobs/macro_state_jobs.py`
- Modify: `src/uw_scan/worker/scheduler.py`
- Modify: `src/uw_scan/api/routers/macro.py`
- Modify: `src/uw_scan/api/routers/gold.py`
- Create: `tests/integration/worker/test_macro_usd_gold_jobs.py`
- Create: `tests/integration/api/test_macro_usd_gold_router.py`
- Modify: `tests/integration/api/test_gold_router_state.py`
- Modify: `web/components/gold/GoldCompassLayout.tsx`
- Modify: `web/tests/e2e/gold-page.spec.ts`

**Steps:**

1. Add USD and gold state jobs reading persisted upstream state; source jobs remain independent.
2. Add `GET /api/macro/usd` and `GET /api/macro/gold` with replay/evidence.
3. Feature-flag the new state/confidence/provenance block on `/gold`; retain the existing response
   during parity.
4. Render structural/cyclical/valuation lenses, shared upstream state, confidence, contradictions,
   missing-source reasons, and evidence drill-down.
5. Surface Part A's market sub-states on `/rates` under R2: each carries its own confidence, and the
   policy-path confidence is never rendered as though it covered them.
6. Remove or relabel any forecast/allocation-like output not backed by a promoted model.
7. Regenerate `web/lib/types.ts` after the API change.

### Task B7: Verification and conditional checkpoint

Run all new source/macro/storage/worker/API tests, existing Gold Compass integration/replay tests,
web unit/e2e tests, type generation, migration idempotence against a **fresh** database, source
probes, and the real worker -> DB -> API -> browser flow. Run `git diff --check`.

Add the `[Unreleased]` CHANGELOG entry on this branch before the PR, not after.

If and only if explicitly authorized, checkpoint with scoped commits at the Part A and Part B seams.

## Exit criteria

Part A:

- `supply`, `positioning` and `plumbing` resolve to real observations with honest availability;
- no evidence row is sourced from a legacy overwrite-on-conflict table;
- `market_factors_absent` reports `0` and the term survives for regression visibility;
- each market sub-state publishes its own confidence and no surface conflates it with the policy
  path's;
- backfilled history is refused for a replay `as_of` before its fetch clock.

Part B:

- USD state uses an official free primary and no static/Yahoo fallback;
- upstream inflation/rates/market-layer evidence is referenced, not duplicated;
- every consumed gold input is present in typed provenance or explicit omissions;
- post-2022 regime gating remains load-bearing;
- Gold replay and legacy compatibility pass;
- no forecast/allocation/sizing claim is promoted;
- real source/worker/database/API/browser verification passes.
