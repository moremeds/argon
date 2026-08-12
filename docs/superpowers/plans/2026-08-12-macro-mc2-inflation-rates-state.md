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
