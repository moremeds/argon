# Macro MC4–MC6 Context Snapshot, PM Integration, and Validation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** assemble the four verified macro domains into a reproducible top-down context snapshot,
attach it to Fundamental PM reports as a removable context block, and run a separate PIT/OOS gate
before any macro state may influence ranking, sizing, or recommendations.

**Architecture:** MC4 persists a snapshot DAG over existing domain-state IDs and renders a macro
decision surface. MC5 joins the snapshot to companies/chains through effective-dated exposure
mappings; the fundamental engine remains invariant. MC6 is research-only and uses the shared
walk-forward harness plus full persisted traces to decide whether any precisely defined macro feature
earns stronger authority.

**Tech Stack:** PostgreSQL/psycopg, Pydantic/FastAPI, APScheduler, Next.js/React, existing Fundamental
PM report/card contracts when landed, and `src/uw_scan/backtest/`.

---

## Preconditions and PR boundaries

- MC2–MC3/GM2 are verified before MC4 code starts.
- MC5 begins only after both MC4 and the Fundamental PM M3/report input-manifest contract are real.
  Re-anchor file paths to the merged PM implementation before coding; do not edit the active P1b
  ingest worktree.
- MC4, MC5, and MC6 are separate PRs. MC6 failure does not roll back MC4/MC5 descriptive context.
- Recheck migration numbering; this plan reserves `117_macro_context_snapshots.sql` for MC4 and
  `118_company_macro_exposures.sql` for MC5.

## MC4 — versioned context snapshot and macro surface

### Task 1: Write snapshot invariants and failing pure tests

**Files:**
- Create: `src/uw_scan/macro/context.py`
- Create: `tests/unit/macro/test_context_snapshot.py`
- Modify: `src/uw_scan/models/macro.py`

**Steps:**

1. Test assembly requires exactly one compatible state for each available domain and never averages
   their confidence/state into a composite score.
2. Test causal order: inflation → rates → USD → gold, with explicit shared contradictions and
   transmission statements.
3. Test missing domains yield `partial` plus reasons; a missing load-bearing upstream domain prevents
   a confident downstream transmission claim.
4. Test same state IDs/method parameters produce the same `inputs_hash`; any changed state ID changes
   it.
5. Implement `MacroContextSnapshot` with domain-state IDs, top-down links, contradictions,
   coverage/freshness, status, `engine_version`, `inputs_hash`, `as_of`, and `computed_at`.

### Task 2: Persist snapshots and exact evidence lineage

**Files:**
- Create: `src/uw_scan/storage/migrations/117_macro_context_snapshots.sql`
- Modify: `src/uw_scan/storage/macro_context.py`
- Modify: `src/uw_scan/reports/data_gap_healer.py`
- Modify: `docs/runbooks/data-gap-dataset-policy.md`
- Create: `tests/integration/storage/test_macro_context_snapshots.py`

**Required tables:**

```text
macro_context_snapshots
  snapshot_id, as_of, computed_at, engine_version, inputs_hash
  status, coverage_jsonb, freshness_jsonb, contradictions_jsonb, transmission_jsonb
  UNIQUE (as_of, engine_version, inputs_hash)

macro_context_domains
  snapshot_id FK, domain, state_id FK, ordinal
  PRIMARY KEY (snapshot_id, domain)

macro_context_evidence
  snapshot_id FK, obs_id FK, domain, causal_role
  PRIMARY KEY (snapshot_id, obs_id, domain, causal_role)
```

Insert idempotently, retain prior versions, register every temporal table, regenerate the policy doc,
and prove arbitrary-date replay reconstructs the same state/evidence DAG.

### Task 3: Add snapshot worker and API

**Files:**
- Modify: `src/uw_scan/worker/jobs/macro_state_jobs.py`
- Modify: `src/uw_scan/worker/scheduler.py`
- Modify: `src/uw_scan/api/routers/macro.py`
- Create: `tests/integration/worker/test_macro_context_job.py`
- Create: `tests/integration/api/test_macro_context_router.py`
- Modify: `web/lib/types.ts` via generation

**Steps:**

1. Assemble from latest compatible domain states available by `as_of`; never fetch providers inside
   the snapshot job.
2. Add `GET /api/macro/context` and `GET /api/macro/context/{as_of}` with evidence drill-down.
3. Test idempotency, stale/partial behavior, mixed engine incompatibility, and provider-independent
   replay.

### Task 4: Build the top-down macro decision surface

**Files:**
- Create: `web/app/macro/page.tsx`
- Create: `web/components/macro/MacroContextDesk.tsx`
- Create: `web/components/macro/DomainStateCard.tsx`
- Create: `web/components/macro/PolicyPathLanes.tsx`
- Create: `web/components/macro/EvidenceDrawer.tsx`
- Create: `web/tests/unit/macro/MacroContextDesk.test.tsx`
- Create: `web/tests/e2e/macro-context.spec.ts`

**Steps:**

1. Render the causal sequence rather than four independent scorecards.
2. Show state, direction, velocity, confidence reasons, contradictions, freshness, and evidence for
   each domain.
3. Show official/SEP/dealer/market policy paths as separate lanes.
4. Show replay/as-of and previous-snapshot delta.
5. Do not render a master score, probability, allocation, or target.
6. Browser-test current, replay, missing domain, stale snapshot, and source-disagreement states.

### Task 5: MC4 real-path verification and conditional checkpoint

Run migrations twice, macro unit/storage/worker/API tests, type generation, web unit/build/e2e, and a
real persisted-evidence → state → snapshot → API → browser smoke. Verify an old snapshot hash
does not change after inserting a later revision.

If and only if explicitly authorized, checkpoint with `feat(macro): add top-down context snapshots`.

## MC5 — context-only Fundamental PM integration

### Task 6: Freeze company/chain macro exposure semantics

**Files:**
- Create: `docs/superpowers/specs/2026-08-12-company-macro-exposure-design.md`
- Modify: `docs/superpowers/plans/2026-08-12-fundamental-pm-agent-program.md`

Define effective-dated, versioned exposure rows:

```text
ticker / chain_id
factor_key
transmission_channel
direction (positive / negative / mixed / unknown)
strength (disclosed numeric or bounded qualitative)
status (disclosed / derived / inferred / disputed / unsupported)
effective_from / effective_to
evidence
exposure_version
```

Do not estimate a beta in production unless a separately persisted PIT study supports it. Manual or
inferred mappings require evidence/status/review; the model cannot silently author them.

### Task 7: Add exposure schema, repository, and review fixtures

**Files:**
- Create: `src/uw_scan/storage/migrations/118_company_macro_exposures.sql`
- Create: `src/uw_scan/storage/macro_exposures.py`
- Modify: `src/uw_scan/storage/repository.py`
- Modify: `src/uw_scan/models/macro.py`
- Create: `tests/integration/storage/test_macro_exposures.py`
- Create: `tests/unit/macro/test_macro_exposure_resolution.py`

Add immutable exposure versions, effective-date overlap checks, typed evidence associations, and
as-of resolution for company and chain. Test disclosed/derived/inferred precedence, expiry, disputes,
and unsupported mappings.

### Task 8: Attach a removable PM macro block

**Files (re-anchor to merged PM paths before implementation):**
- Modify: `src/uw_scan/models/fundamental.py`
- Modify: `src/uw_scan/api/routers/fundamental.py`
- Modify: `src/uw_scan/reports/fundamental_report.py`
- Modify: `src/uw_scan/worker/jobs/fundamental_jobs.py`
- Modify: `web/components/stock/tabs/FundamentalsTab.tsx`
- Create: `tests/integration/api/test_fundamental_macro_context.py`
- Create: `tests/integration/reports/test_fundamental_macro_invariance.py`
- Create: `web/tests/e2e/fundamental-macro-context.spec.ts`

**Steps:**

1. Add optional `macro_context_snapshot_id` and `macro_exposure_version` to the report/card input
   manifest and macro block hash.
2. Assemble company/chain implications deterministically from the snapshot and effective exposure
   rows; label disclosed/derived/inferred/unknown.
3. Keep fundamental facts, derivations, valuation anchors, score dimensions, and their hashes
   unchanged.
4. Add the load-bearing byte-invariance test: run the same fundamental computation with macro block
   enabled and disabled and assert every fundamental output is identical.
5. Provider/macro failure yields an omitted/stale macro block and leaves the last compatible
   fundamental result usable.
6. Render context, evidence, exposure status, and invalidation conditions; do not show a macro-adjusted
   fundamental score.

### Task 9: MC5 real-path verification and conditional checkpoint

Run macro and fundamental unit/integration/API/web suites plus the real report/card worker path. Prove
the macro block can be toggled off without changing fundamental rows or hashes. Run `git diff --check`.

If and only if explicitly authorized, checkpoint with `feat(fundamentals): attach versioned macro
context`.

## MC6 — empirical promotion gate

### Task 10: Preregister the exact target and baselines

**Files:**
- Create: `docs/research/2026-08-12-macro-context-validation/PREREGISTRATION.md`

Before fitting, fix:

- the proposed feature/state and any allowed transformations;
- the exact target (descriptive transition, forward asset return, drawdown risk, or company/chain
  outcome—never a vague “works”);
- horizon, rebalance/decision timing, availability lag, universe, benchmark, and costs;
- train/validation/holdout dates and regime splits;
- simple baselines, ablations, multiple-testing policy, kill thresholds, and promotion authority.

MC6 must not retrofit an attractive target after seeing results.

### Task 11: Build PIT panel and reuse the shared walk-forward harness

**Files:**
- Create: `scripts/research/macro_context_walkforward.py`
- Create: `tests/unit/research/test_macro_context_walkforward.py`
- Reuse: `src/uw_scan/backtest/engine.py`
- Reuse: `src/uw_scan/backtest/gates.py`
- Reuse: `src/uw_scan/backtest/splitters.py`
- Reuse: `src/uw_scan/backtest/metrics.py`
- Reuse: `src/uw_scan/backtest/sweep.py`

**Steps:**

1. Build every decision row with `available_at <= origin` and persist excluded rows/reasons.
2. Use the shared holdout, quarter/regime gates, metrics, and persist-as-you-go sweep; do not copy
   private split/gate math.
3. Compare against price-only, rate-only, and simple-domain baselines appropriate to the target.
4. Run factor and domain ablations, source-vintage sensitivity, regime splits, overlapping-horizon
   robust inference, turnover/cost assumptions, and stability across engine versions.
5. Persist every configuration, metric, gate, trade/event row, error, seed, code/data hash, and exact
   reproduce command before the process exits.

### Task 12: Publish a bounded verdict

**Files:**
- Create: `docs/research/2026-08-12-macro-context-validation/results.json`
- Create: `docs/research/2026-08-12-macro-context-validation/VERDICT.md`
- Create: `docs/research/2026-08-12-macro-context-validation/README.md`

The verdict is one of:

- `descriptive_only`: retain MC4/MC5; no score/ranking/sizing authority;
- `monitor_only`: permit one precisely defined risk/transition monitor;
- `candidate_for_operator_approval`: evidence passes the preregistered PIT/OOS gates, but authority
  still requires a new plan and explicit operator decision.

No MC6 result directly edits production weights or methods.

### Task 13: MC6 verification and conditional checkpoint

Run the research unit tests, reproduction command, `--self-check`, exact artifact-consistency check,
and unchanged shared-backtest regression suites. Inspect the full persisted trace, not only headline
metrics.

If and only if explicitly authorized, checkpoint with `research: validate macro context promotion
gate`.

## MC4–MC6 exit criteria

- context snapshot replays from exact state/observation FKs and remains stable after revisions;
- macro UI exposes causal order, disagreements, confidence, freshness, and unknowns without a master
  score;
- PM integration is context-only and passes byte-invariance tests;
- missing macro context cannot remove or alter fundamental results;
- exposure mappings are versioned/effective-dated/evidence-backed;
- MC6 persists the full PIT/OOS trace and publishes a bounded verdict;
- no ranking, sizing, recommendation, or method change occurs without a new explicit approval gate.
