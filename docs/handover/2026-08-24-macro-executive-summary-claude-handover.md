# Handover: Top-Down Macro Context — executive status and next program

**To:** Claude Code  
**From:** Codex, after a source/DB/API/browser review on 2026-08-23/24  
**Repository:** `/Users/chenxi/projects/argon`  
**Handoff worktree:** `/Users/chenxi/projects/argon/.worktrees/macro-executive-handoff`  
**Branch:** `misc/macro-executive-handoff`  
**Base:** `86161f1d` (`v0.12.16`, merged by PR #379)  
**Status:** documentation handoff only; no macro implementation has been started here  

## Reactivation prompt

> We are continuing the Argon top-down macro program from this handoff. Read this document first,
> then read the cited plans/research and inspect the current repository and production state. Re-check
> every time-sensitive fact; do not assume the old chat is available or that this document authorizes
> implementation, commits, pushes, PM integration, alerts, or signal authority. Preserve the causal
> order `inflation -> policy/rates -> USD -> gold`. Continue from the ordered next steps and stop at
> the stated gates.

---

## 1. Executive decision

The macro program has a real, deployed, point-in-time descriptive foundation. MC0 through MC3 are
substantially implemented: immutable source evidence, FOMC/SEP policy paths, inflation/rates states,
the rates market layer, USD transmission, Gold's regime gate, worker persistence, API replay, and a
new `/macro` page all exist.

The program is **not yet a validated decision system**:

- MC4's atomic `MacroContextSnapshot` does not exist. The page composes four independent latest
  domain responses.
- MC5 Fundamental PM integration is not implemented and is not authorized by this handoff.
- MC6 preflight found that categorical state flips are not a statistically viable validation unit.
  Gold is not historically PIT-replayable before its retrieval-clock evidence began.
- The evidence ledger cannot mark an already accepted observation as subsequently known-bad.
- Two concrete truthfulness defects remain visible in current production: `2/1 load-bearing inputs
  present` for USD and Gold, and Gold state computation occurs before the same day's Gold posture
  compute.

**Recommended authority boundary:** build the next phase as a **risk-monitoring layer** first. It may
report freshness, contradictions, missing domains, dependency incompatibility, and measured
transmission breakdowns. It must not rank, size, recommend, or alter Fundamental PM output.

The user was offered three authority levels — descriptive-only, risk-monitoring, or immediate PM
input — and did not explicitly choose before requesting this handoff. Do not interpret the handoff
request as approval for MC5. Confirm the boundary before any implementation whose scope depends on
that choice.

## 2. Current deployed truth, refreshed 2026-08-24

At handoff time:

- `main` and `origin/main` point to `86161f1d`, tagged `v0.12.16`.
- GitHub Release workflow run `32647680179` completed successfully.
- Mac mini health through `http://100.66.147.98:3001/api/health` reports `ok=true`, `db=up`,
  `version=0.12.16`, and fresh scheduler/worker heartbeats.
- `http://100.66.147.98:3001/macro` returns HTTP 200.
- All four current states were computed with the same exact `as_of`:
  `2026-08-24T07:40:00.001360+08:00`.

| Domain | Engine | State | Direction | Confidence | Evidence rows |
|---|---|---|---|---:|---:|
| inflation | `inflation/1` | `WELL_ABOVE_TARGET` | `FLAT` | 0.3952 | 139 |
| policy_rates | `rates/1` | `ON_HOLD` | `UNKNOWN` | 0.8500 | 580 |
| usd | `usd/2` | `RANGEBOUND` | `FLAT` | 1.0000 | 328 |
| gold | `gold/1` | `SUSPENDED` | `RISING` | 0.8500 | 1,091 |

USD references the current `rates/1` state at the same `as_of`. Gold references the current
inflation, rates, and `usd/2` states at the same `as_of`. This proves the current production row set
is coherent; it does **not** prove the four-latest API composition is safe under a partial nightly
failure.

The deployed page response was about 108 KB. The four backing domain API responses totalled about
673 KB in the review immediately before this handoff, largely because the page fetches full evidence
arrays but uses them only for counts; factors and confidence reasons are what the UI actually
renders.

## 3. Milestone status — facts, not plan labels

| Milestone | Current fact | Honest status |
|---|---|---|
| MC0 | Immutable macro artifact/observation contract merged in PR #332 | merged, with a known invalidation gap |
| MC1 | Durable FOMC/SEP paths merged in PR #348; committed verdict is PASS | merged/PASS, with roster residuals |
| MC2 | Inflation/rates engines, persistence, API, PIT/replay merged in PR #359 | merged and deployed |
| MC3 | Rates market layer, USD, Gold manifest/state merged through PRs #363/#369/#372/#377 | merged and deployed, semantically bounded |
| MC4 | `/macro` causal-chain viewer merged in PR #378; snapshot schema/job/API absent | partial: Task 4 shell only |
| MC5 | Company/chain exposure mapping and removable PM block absent | not started; hold |
| MC6 | State replay census completed; full preregistered PIT/OOS study absent | blocked on a testable object |

The program source-of-truth plan is stale. It incorrectly maps MC1 to PR #359, still labels MC3
`in_progress`, omits `usd/2` and `/macro`, and reserves migrations 117/118 although those numbers are
already used by Fundamentals. Current migration tail is 129. Treat repository/PR history as current
until the plan is repaired.

### Closed work from PRs #377/#378 — do not reopen it

PR #377 did **not** implement hysteresis. Hysteresis was the initial hypothesis and the measured sweep
rejected it: at every tested entry threshold, adding an exit band left transition counts flat or made
them worse. It relocated transitions rather than removing them. The actual lever was the entry
boundary's position in the dollar's own 63-observation move distribution:

| Entry | Distribution percentile | Exit band | Flips | Longest regime |
|---:|---:|---:|---:|---:|
| 2.0% | p61 | none | 29 | 6 months |
| 2.0% | p61 | 1.00% | 26 | 7 months |
| 3.0% | p76 | none | 13 | 14 months |
| 3.0% | p76 | 2.25% | 17 | 12 months |
| 3.0% | p76 | 1.50% | 23 | 7 months |

The shipped change was deliberately one parameter: 2.0% -> 3.0%. Do not reintroduce hysteresis
machinery without new, preregistered evidence that overturns this sweep.

The same PR closed an engine-identity defect. `engine_version` is a read selector, not decorative
metadata: changing only `UsdParameters.version` while leaving `USD_ENGINE_VERSION` unchanged would
publish changed semantics under the old identity. Tests now assert parameter/engine identity for all
four domains. Preserve that convention for every future engine change.

PR #378 intentionally shipped only the descriptive four-domain chain. It also exposed a test-design
lesson: a banned-substring scan for words such as `allocation` flags the Gold disclaimer _"never
becomes a price target, an allocation, or a size"_ as if it were a recommendation. Test that the desk
does not synthesize prohibited authority; do not scan the entire rendered payload for words that may
appear inside an explicit denial.

The original PR-completion note said these commits were not deployed. That statement is now obsolete:
v0.12.16 is deployed, `/macro` returns 200, and the latest stored USD state uses `usd/2`.

## 4. Required reading, in order

1. `CLAUDE.md` — project rules and live architecture.
2. `docs/superpowers/archive/plans/2026-08-12-top-down-macro-context-program.md` — intended program, but
   reconcile its stale status table against this handoff and Git history.
3. `docs/superpowers/archive/plans/2026-08-12-macro-mc4-mc6-context-pm-validation.md` — original MC4–MC6
   design; do not execute its migration numbers or original sequencing literally.
4. `docs/research/2026-08-23-macro-state-replay-flip-census.md` — the binding empirical preflight
   that changes MC5/MC6 sequencing.
5. `docs/research/2026-08-12-fomc-sep-source-probe/VERDICT.md` — current MC1 PASS and its explicit
   residual limitations.
6. `docs/research/2026-08-21-rates-market-layer-probe/VERDICT.md` — WRESBAL unit rebase and rates
   source decisions.
7. `docs/superpowers/archive/specs/2026-08-12-usd-gold-state-design.md` — USD/Gold scope limits and design
   deviations.
8. `src/uw_scan/macro/`, `src/uw_scan/worker/jobs/macro_state_jobs.py`,
   `src/uw_scan/worker/scheduler.py`, `src/uw_scan/api/routers/macro.py`, and
   `web/app/macro/page.tsx` — current implementation.

## 5. Binding findings

### F1 — state labels are not a valid MC6 test unit

`docs/research/2026-08-23-macro-state-replay-flip-census.md` replayed 68 monthly instants from
2021-01 through 2026-08:

- inflation: 4 state flips;
- policy/rates: 8 state flips;
- retired `usd/1`: 29 flips, largely threshold chatter;
- `usd/2`: 13 flips after moving the momentum boundary from 2% to 3%; semantically better, still
  underpowered;
- Gold: historical observations have retrieval-time `available_at`, so the domain is structurally
  unavailable for replay before 2026-08-23.

Do not backfill replayed states into `macro_domain_states`. Those rows are immutable, would bake in
today's engine version, and would manufacture a sample that remains unsuitable.

**Required correction:** run a separate continuous-feature availability and target preflight before
building MC5 or the formal MC6 harness. Candidate units may include continuous factor values,
confidence terms, contradictions, or precisely defined transmission residuals. Fix the target,
horizon, lag, baseline, sample gate, and kill rule before fitting.

### F2 — known-bad evidence remains `valid`

WRESBAL was rejected because FRED republished its history 1,000x on 2025-11-13 while the single-series
contract still labels all vintages `millions_usd`. The local evidence store currently holds 1,173
WRESBAL rows, all 1,173 marked `valid`. For period 2025-06-04 it holds both `3294.381` and
`3294381.0`, both `millions_usd`, both `valid`.

Current FRED contracts correctly exclude WRESBAL, so today's rates state does not consume it. The
architectural defect remains: the immutable ledger has no additive mechanism to say an accepted
artifact/observation/range was later discovered invalid.

**Required correction:** design a versioned invalidation overlay; never mutate or delete raw evidence.
It should support at least:

- artifact, observation, and bounded series/vintage targets;
- `invalidated_at`, reason, evidence, reviewer, and version;
- current/corrected reads that exclude invalidated evidence;
- an explicit decision on whether historical-belief replay preserves what Argon believed before the
  invalidation was discovered.

This needs its own design/spec and PR. Do not hide it inside MC4.

### F3 — `/macro` is not MC4's atomic context snapshot

`web/app/macro/page.tsx` runs four independent latest requests with `Promise.all`. The nightly worker
normally uses one `as_of` and the correct causal order, but each domain job catches its own exception
and the loop continues. If rates fails, USD can consume an older rates state and still persist a new
USD state; Gold can then consume a mixture. The page does not compare top-level hashes/timestamps to
dependency-edge hashes/timestamps.

**Required correction:** implement the actual snapshot DAG from the MC4 plan, using a new migration
number after 129:

- `macro_context_snapshots`;
- one domain edge per available compatible state;
- exact evidence lineage;
- `complete | partial | incompatible | stale` status with reasons;
- idempotent `inputs_hash` over state identities and parameters;
- current/replay APIs;
- a compact summary response and lazy evidence endpoint;
- the page reads one stored snapshot, never four latest answers.

### F4 — confidence explanation is false in current production

Both USD and Gold currently render:

```text
completeness 1 — 2/1 load-bearing inputs present
```

`src/uw_scan/macro/confidence.py` computes numerical completeness from the required-series
intersection, but formats the detail with `len(factors)`. Optional factors also enter freshness,
quality, and revision terms even though they do not enter completeness.

**Required correction:** first freeze semantics in tests:

- the detail count must report required inputs present / required inputs;
- explicitly decide whether optional factors affect freshness, quality, and revision penalties;
- removing an optional factor must not silently improve confidence unless that behavior is deliberate
  and documented.

This is the safest small first implementation PR once the user authorizes coding.

### F5 — Gold reads a posture gauge produced on a later schedule

Scheduler order is:

- 19:30 ET: macro Gold evidence ingest;
- 19:40 ET: all four macro domain states;
- 21:00 ET: legacy Gold posture compute.

Gold state calls `fetch_gold_posture_as_of(as_of.date())`, so the same day's posture cannot exist yet.
The API exposes `gauge_age_days`, which currently reports 2 days across the weekend; the age is
honest, but the schedule guarantees the state never sees the same day's 21:00 posture during the
19:40 pass.

**Required correction:** either compute posture before the macro state, rerun only Gold after posture,
or split Gold snapshot assembly. Add a scheduler-order test and a real persisted smoke that compares
state `as_of`, gauge observation date, and allowed lag.

### F6 — USD and Gold names must remain semantically bounded

- USD `usd_against_relative_policy` currently observes only the US policy leg; there is no foreign
  policy differential. Plumbing and positioning are intentionally refused until a stated rule uses
  them. Do not market this as a complete global relative-policy transmission model.
- Gold's domain state owns two citable inputs (`GLD_CLOSE`, `GLD_HOLDINGS_OZ`) and borrows real-yield
  and USD evidence. Central-bank reserves, exchange inventory, COT, and UW options remain on the
  broader Gold Compass/warm-store path. The state is a narrow relationship gate, not a complete Gold
  investment view.

### F7 — MC1 PASS is real but not perfect

Do not regress the current PASS to the older worktree handover's PARTIAL. The committed result is
55/55 statements, 25/25 SEP, real worker -> DB -> API, idempotency, PIT/correction, and offline replay.

Residuals:

- two statements publish a vote tally without a roster;
- the parser does not capture `Absent and not voting ...` for 2025-07-30;
- CI's frozen regression corpus is 11 statements and 7 SEP releases, while 55/25 is a dated live
  measurement;
- roster/tally checks are not fully independent of the parser that produced them.

Capture the absence format and strengthen reconciliation, but do not block MC4 integrity work on it.

## 6. Recommended delivery sequence

### Step 1 — repair the source-of-truth documents

Update the macro program plan to reflect PRs #332/#348/#359/#363/#369/#372/#377/#378/#379,
`usd/2`, deployed `/macro`, MC4 partial status, current migration numbers, and the replay census's
sequencing change. Label the current page **MC3.5 descriptive chain viewer** rather than a completed
MC4.

**Stop when:** the plan agrees with repository and production state and contains no obsolete migration
reservation.

### Step 2 — land small truthfulness fixes as separate PRs

Recommended order:

1. confidence semantics/detail;
2. Gold posture/state schedule ordering;
3. FOMC absence fixture/reconciliation follow-up.

Do not bundle these with snapshot schema work.

**Stop when:** targeted unit/integration tests and real API/browser smoke show correct explanations,
the intended Gold gauge lag, and no MC1 regression.

### Step 3 — design and implement evidence invalidation

Write the design first. Preserve raw bytes and observation identities. Specify historical-belief vs
corrected-history semantics and the query contract before the migration.

**Stop when:** WRESBAL remains physically present, current/corrected readers exclude it, the reason is
auditable, migration replay is idempotent, and PIT behavior is covered by tests.

### Step 4 — implement the real MC4 snapshot

Split into independently reviewable PRs:

1. snapshot contract + migration + repository;
2. assembler + worker + API;
3. UI migration to snapshot + replay/delta/evidence drawer;
4. real persisted state -> snapshot -> API -> browser verification artifact.

**Stop when:** a partial domain failure can never appear as a coherent fresh chain, a later evidence
revision does not change an old snapshot hash, and the page no longer fetches four latest states.

### Step 5 — run continuous-feature discovery before MC5

Persist the full availability census and every candidate definition. Decide the testable object before
building the walk-forward harness. Do not fit if the preregistered minimum sample gate fails.

**Stop when:** there is either a defensible PIT panel and precise target, or a committed
`descriptive_only` verdict.

### Step 6 — ask for explicit authority before MC5

Only after Steps 1–5 should the user decide whether macro remains descriptive/risk-monitoring or may
enter the Fundamental PM surface. If MC5 is authorized, keep it removable and prove byte-invariance
of every fundamental fact, score, valuation anchor, and hash with macro on/off.

**Stop when:** authority is explicit; an empirical result never edits production ranking/sizing by
itself.

## 7. Completion gates Claude must preserve

Before anyone calls the macro program complete:

1. Known-bad evidence can be invalidated additively without deleting raw evidence.
2. Confidence reasons and arithmetic refer to the same load-bearing set.
3. Gold state/gauge timing is deliberate, tested, and exposed.
4. One persisted context snapshot owns the four-domain composition and exact lineage.
5. Missing, stale, failed, or incompatible domains produce `partial`/refusal, never a coherent-looking
   full chain.
6. Historical replay uses only evidence available by the selected instant; later revisions do not
   mutate stored answers.
7. MC6 uses a preregistered, sufficiently sampled target and persists the full trace before exit.
8. No alert, PM overlay, ranking, sizing, recommendation, or allocation authority is inferred from a
   descriptive state.
9. Real smoke follows worker -> DB -> API -> browser. Direct function scripts do not satisfy the
   production gate.
10. CHANGELOG, docs, code, tests, and verification evidence ride the same feature PR.

## 8. Worktree and repository boundaries

This handoff worktree was created from clean `main@86161f1d`. The primary checkout at
`/Users/chenxi/projects/argon` had unrelated user-owned changes when this worktree was created:

- modified `docs/research/2026-08-23-fundamental-filing-date-recovery/VERDICT.md`;
- modified `docs/superpowers/plans/2026-08-23-fundamental-calendar-ingest-and-filing-dates.md`;
- untracked `docs/research/2026-08-23-radon-new-features-port-analysis.md`.

Do not copy, revert, commit, or clean those files from this worktree.

Two older macro worktrees are stale and dirty:

- `.worktrees/macro-topdown-pm-plan`;
- `.worktrees/macro-fomc-sep-policy-paths`.

Do not treat either as current source and do not remove them without first preserving their uncommitted
contents and receiving user approval.

Standing boundaries:

- no commit without explicit user request;
- never push directly to `main`;
- open and merge a PR, then align local main;
- migrations idempotent;
- `uv` only;
- no Yahoo;
- no naked shorts;
- no secrets to local model subprocesses;
- do not extend `storage/repository.py`; use the existing domain mixin/module boundary;
- do not backfill replayed macro states merely to increase sample size.

## 9. Verification already run

Source review before creating this worktree:

```text
uv run pytest tests/unit/macro tests/unit/sources/test_fred_macro.py \
  tests/integration/api/test_macro_state_router.py \
  tests/integration/worker/test_macro_state_jobs.py \
  tests/integration/worker/test_macro_gold_state_job.py -q
-> 295 passed

cd web && npm run test -- tests/unit/macroDesk.test.tsx
-> 1 file, 9 tests passed
```

All macro PRs listed above had seven successful CI checks. The v0.12.16 release workflow completed
successfully. Production health/API/page checks were repeated while writing this handoff and produced
the deployed truth in section 2.

Baseline verification inside this new worktree is recorded below after the handoff file is written:

```text
uv sync --extra postgres
-> success; isolated .venv created and uw-scan 0.12.16 installed

uv run pytest tests/unit/macro tests/unit/sources/test_fred_macro.py \
  tests/integration/api/test_macro_state_router.py \
  tests/integration/worker/test_macro_state_jobs.py \
  tests/integration/worker/test_macro_gold_state_job.py -q
-> 295 passed

cd web && npm install
-> dependencies installed; npm reported 13 dependency-audit findings
   (1 low, 1 moderate, 9 high, 2 critical). This handoff did not run npm audit fixes or alter the
   dependency graph; package-lock version churn created by npm install was reverted.

cd web && npm run test -- tests/unit/macroDesk.test.tsx
-> 1 file, 9 tests passed

git diff --check
-> clean
```

## 10. First Claude Code actions

1. Run `git status --short --branch` and verify the branch/path/base above. Stop if the worktree has
   changes other than this handoff that are not explained here.
2. Read the eight required sources in section 4 and confirm the documented status still matches
   repository, GitHub, and production.
3. Ask the user to confirm the next authority boundary if it is still unresolved. Recommend
   risk-monitoring, not immediate PM authority.
4. Present a small design for Step 1 plus the first truthfulness PR. Do not start MC4 or MC5 in this
   documentation branch.
5. If implementation is approved, create a fresh canonical `.worktrees/<branch-slug>/` worktree for
   the chosen PR, use TDD, and keep each PR independently reviewable.
6. Before claiming completion, rerun the relevant unit/integration/web tests and a real deployed-path
   smoke, then report any drift from this handoff.
