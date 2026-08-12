# Macro MC3 USD Transmission and Gold State Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** add a free-first USD-transmission state, adapt Gold Compass to the shared macro evidence
contract, and guarantee that every gold output references all inputs it actually consumed.

**Architecture:** USD is a transmission domain, not a duplicate inflation/rates score. It consumes
shared upstream state IDs plus official broad-dollar, relative-policy, funding/liquidity, and
positioning evidence. Gold preserves its three lenses—structural flow, regime-gated cyclical, and
valuation overlay—but emits a versioned macro domain state with complete typed provenance.

**Tech Stack:** FRED/Federal Reserve H.10, BIS SDMX/CSV, CFTC, existing Gold Compass sources and
cards, MC0/MC2 storage/contracts, FastAPI and React.

---

## Preconditions and PR boundary

- MC2 is verified; shared real-yield, inflation-compensation, policy-path, and broad-dollar ownership
  is fixed.
- Recheck endpoint availability before choosing BIS/Fed adapters and persist live-probe evidence.
- Do not add Yahoo/yfinance, a DXY `static` fallback, a gold price target, allocation, or sizing.
- Existing `/gold` remains usable throughout dual-read.

### Task 1: Preregister USD and gold causal roles

**Files:**
- Create: `docs/superpowers/specs/2026-08-12-usd-gold-state-design.md`
- Create: `tests/fixtures/macro/usd_gold_golden.json`

Define:

- upstream shared inputs versus domain-owned inputs;
- USD transmission factors: broad effective dollar, real/relative policy, funding/liquidity,
  positioning, and risk transmission;
- Gold Lens 1 structural flows, Lens 2 regime-gated cyclical factors, and Lens 3 valuation overlay;
- contradiction, missingness, freshness, and confidence rules;
- explicit prohibition on counting real yields, inflation compensation, or USD twice.

Golden scenarios must include policy/USD disagreement, post-2022 gold/real-yield decoupling, strong
central-bank/ETF flows with adverse cyclical inputs, and stale/missing COMEX/WGC inputs.

### Task 2: Add official USD source probes and parsers

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

### Task 3: Implement pure USD transmission state

**Files:**
- Create: `src/uw_scan/macro/usd.py`
- Create: `tests/unit/macro/test_usd_state.py`
- Modify: `src/uw_scan/models/macro.py`

**Steps:**

1. Write golden-scenario tests first.
2. Consume MC2 inflation/rates state IDs rather than recomputing their inputs.
3. Treat broad-dollar level/momentum, relative policy, liquidity/funding, and CFTC positioning as
   separate factors; preserve contradictions.
4. Define velocity horizons in configuration and include them in `engine_version/inputs_hash`.
5. Abstain when the official broad-dollar anchor is missing; no static or third-party substitute may
   silently become primary.

### Task 4: Build complete Gold Compass evidence mapping

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
2. Replace the four-entry `inputs_used` manifest with typed evidence associations for all consumed
   rows. An optional absent input is recorded as an omission reason, not a fake evidence ID.
3. Preserve the three lens outputs and the post-2022 regime gate. Lens 3 remains a valuation warning,
   never a sizing input.
4. Emit a `MacroDomainState(domain="gold")` referencing the existing deterministic lens result and
   shared MC2/MC3 upstream states.
5. Verify old replay dates still render and new replay reconstructs the exact evidence manifest.

### Task 5: Persist USD/gold states and cross-domain lineage

**Files:**
- Modify: `src/uw_scan/storage/macro_context.py`
- Modify: `src/uw_scan/storage/migrations/116_macro_domain_states.sql` only if MC2 left planned
  generic fields unused; otherwise create the next additive migration
- Modify: `tests/integration/storage/test_macro_context_repository.py`

**Steps:**

1. Persist USD/gold through the same `macro_domain_states` contract as inflation/rates.
2. Add typed state-to-state dependency associations if they were not included in MC2:
   `(downstream_state_id, upstream_state_id, causal_role)`.
3. Test the same upstream state can be referenced by USD and gold without copying observations.
4. Test a changed upstream state changes downstream `inputs_hash` and preserves the predecessor.

### Task 6: Add jobs, API, and dual-read Gold/UI integration

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
5. Remove or relabel any forecast/allocation-like output not backed by a promoted model.

### Task 7: Verification and conditional checkpoint

Run all new source/macro/storage/worker/API tests, existing Gold Compass integration/replay tests,
web unit/e2e tests, type generation, migration idempotence, source probes, and the real worker → DB
→ API → browser flow. Run `git diff --check`.

If and only if explicitly authorized, checkpoint with a scoped `feat(macro): add USD and gold state
adapters` commit.

## MC3 exit criteria

- USD state uses an official free primary and no static/Yahoo fallback;
- upstream inflation/rates evidence is referenced, not duplicated;
- every consumed gold input is present in typed provenance or explicit omissions;
- post-2022 regime gating remains load-bearing;
- Gold replay and legacy compatibility pass;
- no forecast/allocation/sizing claim is promoted;
- real source/worker/database/API/browser verification passes.
