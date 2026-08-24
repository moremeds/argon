# Fundamental PM Research System — Claude Code Executive Handover

> **Reactivation prompt:** Continue Argon's Fundamental PM Research System from this handoff. Read
> repository `CLAUDE.md`, the reconciled design, the master program plan, and the Pre-Job 0 child
> plan before editing code. Reverify Git and test state; do not rely on chat history. Execute only
> the next gated child project, preserve explicit non-goals, and stop before commit/push/PR or
> production mutation unless the user separately authorizes it.

## 1. Executive summary

You are taking over the full Fundamental PM Research System program—not a single as-of repair and
not a Radar-only feature—in this isolated worktree:

- repository: `/Users/chenxi/projects/argon`
- worktree: `/Users/chenxi/projects/argon/.worktrees/fundamental-pm-research-system`
- branch: `feat/fundamental-pm-research-system`
- baseline commit: `86161f1da6c3b7ed5a31ee0409ba814ce7d9dd85`
- baseline release: `v0.12.16`
- primary checkout branch: `main`

The approved product is one evidence-driven system with:

1. point-in-time source evidence;
2. a deterministic company engine;
3. a Fundamental PM Research Radar for attention routing;
4. a general industry-chain/exposure product;
5. versioned audited research reports;
6. a bounded refresh/draft agent harness.

The immediate executable project is **Pre-Job 0: observation-version as-of correctness**. It must
land before corrected historical research or stronger Radar claims. It is a pre-job, not a scope
reduction of the larger program.

## 2. Read these documents in order

1. `CLAUDE.md`
2. `docs/superpowers/specs/2026-08-24-fundamental-pm-research-system-design.md`
3. `docs/superpowers/plans/2026-08-24-fundamental-pm-research-system-program.md`
4. `docs/plans/2026-08-24-fundamental-observation-asof.md`
5. this handoff

Historical context, not the future execution source of truth:

- `docs/superpowers/specs/2026-08-10-fundamental-pm-agent-design.md`
- `docs/superpowers/plans/2026-08-12-fundamental-pm-agent-program.md`

The 2026-08-12 plan has been marked superseded for future sequencing but intentionally retained as
the record of original decisions, measured research, and shipped milestones.

## 3. The master decision

Do not reinterpret the plan as “build an evidence-driven Radar.” The Radar is the portfolio-level
entry surface inside a larger research product.

The north-star flow is:

```text
question / event / scheduled review
  -> freeze scope, as-of, evidence policy, taxonomy, methods, budget
  -> deterministic company and chain calculations
  -> Radar attention routing
  -> company/comparison/chain drill-down
  -> versioned report and prior-version delta
  -> optional audited narrative
  -> bounded agent refresh/draft loop
```

Industry-chain research is first-class. The general schema is:

```text
research_domain -> industry -> layer -> chain -> company_exposure -> evidence
```

AI infrastructure is the first content pack. Optical communication is the required proof that a
new sub-chain can be added without changing the engine, report ledger, or agent workflow.

The composite is research priority only. It is not expected return, a buy score, portfolio weight,
or trade instruction. Null or mixed empirical results reduce claim authority; they do not remove the
company, chain, or report product.

## 4. Current shipped state

At `v0.12.16`, Argon already has:

- `fundamental_statement_obs` and immutable content-hash observation identity;
- UW statement ingest/backfill and scheduled incremental ingest;
- deterministic feature, score, and valuation-anchor computation;
- `fundamental_scores` and `valuation_anchors` persistence;
- nightly zero-provider-spend `fundamental_refresh` for routing/scoring/anchors;
- `/fundamentals` and `/fundamentals/statements` stock APIs;
- the stock-page Fundamentals tab and component panels;
- filing-date recovery and future-knowledge cutoff fixes;
- a first concentration capture implementation;
- many-to-many watchlist chain membership;
- 209 passing targeted fundamentals tests in the baseline run before the worktree rename.

Production was verified on 2026-08-24:

- release workflow `32647680179` succeeded;
- `/api/health` reported `ok: true`, version `0.12.16`;
- the filing-date recovery backfill reported 450 tickers, 89,553 touched observations, zero inserts,
  zero failures, and 8,520 tolerance-path dates filled;
- NULL `filing_published_at` rows fell from 43,210 to 34,690;
- the 2020-and-later panel was 91.1% dated.

Treat these production figures as dated evidence and reverify before a release claim.

## 5. Ownership boundary: primary checkout is dirty

The following production evidence is currently in uncommitted **user-owned changes in the primary
checkout**, not this worktree:

- `docs/research/2026-08-23-fundamental-filing-date-recovery/VERDICT.md`
- `docs/superpowers/plans/2026-08-23-fundamental-calendar-ingest-and-filing-dates.md`

The primary checkout also has an unrelated untracked file:

- `docs/research/2026-08-23-radon-new-features-port-analysis.md`

Do not copy, overwrite, clean, commit, stash, or otherwise alter those files unless the user
explicitly requests it. This worktree starts from the committed `v0.12.16` state.

## 6. Worktree state at handoff

Expected uncommitted changes are documentation only:

- new reconciled system design;
- new master program plan;
- new Pre-Job 0 child implementation plan;
- this renamed/revised handoff;
- a supersession notice at the top of the 2026-08-12 program plan.

No application code, migration, test, changelog, commit, push, PR, or production mutation has been
performed for the new program in this worktree.

The worktree moved from `.worktrees/fundamental-observation-asof` after its original `uv sync`.
The environment has now been reinstalled at the new path because Python console-script shebangs had
retained the old absolute path.

## 7. Why Pre-Job 0 is blocking

The existing storage gets content identity mostly right:

- normalized content hashes exclude UW `inserted_at`/`updated_at` envelope fields;
- unchanged fetches touch `last_seen_at` without a new fact row;
- changed content creates a new immutable observation;
- a missing `filing_published_at` may be filled but an existing one is not overwritten;
- future knowledge-date estimates are withheld.

But the current reader is not a true as-of reader:

- `src/uw_scan/storage/fundamental_obs.py::statement_panel()` selects the maximum `obs_id` for each
  `(ticker, period_end, statement)`;
- `src/uw_scan/worker/jobs/fundamental_scoring.py` builds historical knowledge-date buckets from that
  current-vintage panel;
- a restatement captured in 2023 can therefore be used in a bucket representing 2020/2021;
- `filing_published_at` describes the original filing and does not prove when the specific later
  content hash became public;
- `first_observed_at` proves capture, not original market publication;
- old backfilled snapshots do not reconstruct a revision timeline.

This is a live correctness issue: multiple content versions already exist for historical identities.
Do not rerun or strengthen historical signal research until the reader contract is corrected.

## 8. Required Pre-Job 0 outcome

Implement append-only version-availability evidence with these minimum classes:

- `true_pit`: positive version-level publication/amendment evidence;
- `capture_bounded`: safely usable no earlier than capture of that exact content;
- `current_vintage`: usable for today's current panel, not historical replay;
- `unknown`: no usable version timestamp.

Provide two separate read contracts:

1. current panel: newest accepted content for today's page;
2. as-of panel: versions admitted by a required evidence policy at the cutoff.

Legacy rows may receive current-vintage classification and a conservative capture-bounded claim at
their persisted `first_observed_at`. They must not receive true-PIT merely because an original filing
date is populated.

Historical scoring must explicitly name its evidence policy and bind selected versions/policy to
result identity. Existing old score/anchor rows remain untouched and visibly old/current-vintage.

## 9. Ordered next steps

1. **Reverify Git state.** Confirm branch/worktree/baseline and that no unexpected code edits exist.
2. **Refresh dependencies.** Run `uv sync --extra postgres` after the worktree move.
3. **Re-run the targeted fundamentals baseline.** Record exact pass/fail/skip count; stop on unrelated
   baseline failure.
4. **Execute the Pre-Job 0 child plan task by task.** Use test-first development and keep each task's
   explicit non-goals.
5. **Freeze pure terminology before SQL.** Classes, timestamps, and policy admission must be
   unambiguous.
6. **Add an additive availability-claim migration.** Confirm the next migration number is still free.
7. **Implement append-only claim persistence and honest legacy classification.** No guessed PIT.
8. **Write the decisive SQL reader tests.** Original 2020 version versus 2023 restatement, current
   versus true-PIT versus capture-bounded.
9. **Split readers and protect current consumers.** Keep today's card/anchors compatible.
10. **Make historical scoring policy explicit.** Do not globally cut over unmeasured production
    coverage.
11. **Run migration idempotency, targeted/full tests, Ruff, no-Yahoo, and diff checks.** Record exact
    results.
12. **Report class distribution and blocked historical spans.** Production backfill only with user
    authorization.
13. **Stop for review.** No commit, push, PR, or production change without a new explicit instruction.

After Pre-Job 0 review, the next program work is M1: input-eligibility enforcement, multi-source
canonical evidence, typed provenance, and governed company identity/type. Write its child plan from
the observed availability-class distribution rather than guessing it in advance.

## 10. Pre-Job 0 completion gates

All must hold:

- current and as-of reader contracts are explicit and documented;
- a later restatement cannot enter an earlier true-PIT replay;
- unknown revision time fails closed;
- capture-bounded rows enter only at/after conservative capture time;
- current-page and current-anchor behavior remains compatible;
- unchanged refresh and filing-date recovery remain idempotent;
- historical score identity includes evidence policy and selected version lineage;
- migration reruns are no-ops;
- real SQL integration tests prove selection order;
- class coverage and unsupported historical spans are reported;
- existing rows/results are preserved;
- no research claim was promoted;
- only intended worktree files are dirty;
- no unauthorized GitHub, production, or primary-checkout mutation occurred.

## 11. Whole-program milestone gates

Do not continue automatically from Pre-Job 0 into the rest of the system. Each milestone gets a
child plan after the predecessor evidence is reviewed.

| Milestone | Outcome | Gate before moving on |
|---|---|---|
| P0 | honest version availability and as-of reader | restatement/cutoff SQL proof |
| M1 | canonical evidence, input validity, typed provenance, governed entities | real ingest/canonical replay |
| M2 | deterministic engine v2 and run ledger | worked examples/hash/refusal proof |
| M3 | corrected research and claim permissions | durable rerun and explicit authority |
| M4 | company v2 and Radar | real worker/API/browser states |
| M5 | general chain/exposure product | evidence-backed optical proof |
| M6 | filings/catalysts/risks/concentration | extraction yield/precision and amendment routing |
| M7 | versioned deterministic reports | old-report replay and delta |
| M8 | optional narrative and claim audit | provider-down and adversarial audit proof |
| M9 | bounded agent harness | least privilege, budgets, dedupe, one-week soak |

Stronger investment ranking is outside this sequence unless active-plus-delisted PIT/OOS, regime,
cost, and explicit operator gates pass in the optional empirical track.

## 12. Other known problems that Pre-Job 0 must not absorb

These are real and already placed in later milestones:

- integrity violations currently suppress display but can still influence composite math;
- UW-only backbone and incomplete SEC/Massive canonical reconciliation;
- FK-less `source_obs_ids BIGINT[]` provenance;
- large company-type classification gap;
- valuation research's raw-close/current-split-basis-shares mismatch;
- UI no-data/error/stale conflation;
- concentration as a first snapshot rather than multi-period ledger;
- taxonomy membership without evidence-backed exposure;
- no report ledger or bounded agent surface;
- near-1,000-line valuation/anchor modules.

Do not opportunistically fix them in Pre-Job 0. The point of the master plan is to preserve them as
ordered work rather than lose them in one oversized correctness PR.

## 13. Verification previously performed

Before and during the worktree rename/plan rewrite:

- `.worktrees/` existed and was ignored;
- the original isolated branch/worktree was created from committed `main` at `86161f1d`;
- `uv sync --extra postgres --reinstall` rebuilt the moved environment and `pytest --version`
  succeeded from the new absolute path;
- the targeted fundamentals suite completed again after the move with `209 passed`;
- production release/health and filing-date backfill evidence above were checked.

These are starting evidence, not a completion claim. Re-run local verification after the worktree
move and re-check production drift before any release statement.

---

## 14. Pre-Job 0 execution record — 2026-08-24

Executed task-by-task from `docs/plans/2026-08-24-fundamental-observation-asof.md`.
**Stopped before commit, push, PR, and any production mutation**, as instructed.

### Verified state

| Check | Result |
|---|---|
| Baseline (targeted fundamentals, before any edit) | `209 passed` |
| Targeted suite (after) | `334 passed` |
| Full `uv run pytest` | `4031 passed, 14 skipped, 0 failed` (7:54) |
| `ruff check src/ tests/ scripts/` | clean |
| `scripts/check_no_yahoo.py` | clean |
| `git diff --check` | clean |
| Migrations applied twice on a fresh DB | both passes OK; constraints/indexes/columns verified from a new connection |
| Primary checkout | unchanged — same 4 user-owned files as at handoff |

### What shipped

- `fundamentals/observation_time.py` — four evidence classes, two historical
  policies, timestamp validation, versioned rule keys, audit self-checks.
- Migration `130` — append-only `fundamental_obs_availability`, two CHECK
  constraints binding the instant to the classes that earn one,
  `UNIQUE (obs_id, claim_key)`.
- Migration `131` — `evidence_policy` / `as_of_cutoff` / `availability_ids` on
  `fundamental_scores`, additive, existing rows default to `current_vintage`.
- `storage/fundamental_observation_availability.py` — claim persistence, set-based
  keyset seeding, coverage audit. No update path exists in the module.
- `storage/fundamental_observation_panels.py` — `current_statement_panel` and
  `statement_panel_as_of`. `FundamentalObsRepository.statement_panel` is now a
  documented alias to the former.
- `worker/jobs/fundamental_observation_availability.py` + backfill script — legacy
  classification, zero provider spend, resumable, `--counts` / `--audit` modes.
- `fundamental_ingest` claims availability for every version it persists; a claim
  failure marks the ticker FAILED rather than reporting success.
- `fundamental_scoring` takes `evidence_policy` with no historical default.
- Runbook `docs/runbooks/fundamental-observation-availability.md`; audit README
  `docs/research/2026-08-24-fundamental-observation-availability/`.
- `fundamental_obs_availability` registered with the gap healer as `provenance`;
  `docs/runbooks/data-gap-dataset-policy.md` regenerated (it is generated — a
  hand edit fails `test_committed_policy_doc_is_in_sync_with_registry`).
- `CHANGELOG.md` `[Unreleased]` entry added on the branch.

### Deviations from the plan, and why

1. **As-of partition excludes `source`.** The plan specified `(source, ticker,
   period_end, period_type, statement)`, but the panel's output shape has no
   source dimension and the current reader dedupes across sources. Adding it
   would silently last-write-wins the moment M1 lands a second source. Partition
   matches the current reader; cross-source precedence is M1's, which owns
   canonical reconciliation.
2. **Job tests live in `tests/integration/worker/`, not `tests/unit/worker/`.**
   The classification job is entirely SQL; a unit test would need a fake DB, which
   the suite bans.
3. **`data-gap-dataset-policy.md` was regenerated, not edited** (plan Task 5 Step 4
   said "modify"). It is generated from `REGISTRY` and byte-asserted in CI.
4. **The new table IS registered with the healer.** The migration first argued it
   needed no entry; `test_data_gap_full_coverage.py` scans the live schema and
   requires universal enrollment. Registered as `provenance` with a dated reason.
5. **No per-bucket panel re-read in scoring.** A replay buckets each row by its own
   version's `available_at`, which is leak-free by construction and costs one
   panel read. The consequence is stated in code and pinned by
   `test_a_late_run_cannot_reproduce_an_early_bucket`: a run at a late cutoff
   cannot reproduce an early bucket, because superseded versions have moved
   forward. Reconstructing bucket B means running with the cutoff inside B.
6. **`inputs_hash` omits the policy key in current mode.** Adding it
   unconditionally would change the hash of every existing score row, making none
   of them reproducible and giving each a duplicate sibling on the next run. The
   asymmetry is documented in the function and pinned by a test.

### Gate status — ALL MET as of 2026-08-24

The final item (production class distribution and unsupported historical spans)
was authorized and executed. Migrations 130/131 applied to `option_wizard`
out-of-band and re-applied cleanly; classification backfill run (89,758 scanned,
179,516 claims, 0 unclaimed, 23.6s, zero provider spend); re-run inserted 0;
`--audit` self-checks passed. Artifact:
`docs/research/2026-08-24-fundamental-observation-availability/`.

### What production actually showed — and where the plan's premise was wrong

1. **The whole statement table was captured in 8 days** (2026-08-16 → 2026-08-23)
   while its periods span 1998 → 2026. Every availability claim therefore sits in
   that window.
2. **The `obs_id` ordering bug had ZERO measured effect.** Over all 200
   multi-version identities, `ORDER BY obs_id DESC` and availability ordering
   select the *same* version — necessarily so, because `capture_bounded`
   availability IS `first_observed_at` and `obs_id` is a BIGSERIAL assigned at the
   same insert. They are monotonic by construction and can never disagree until
   `true_pit` evidence exists. The plan's premise — a 2023-captured restatement
   contaminating a 2021 replay — is not what production contains.
3. **What genuinely changed is the refusal.** At cutoff 2020-06-30 the old path
   served 404 balance-sheet periods for 5 sample names; the as-of reader serves 0.
   Those 404 were all captured in August 2026. The old answer was fiction.
4. **97.8% of the score history is unsupported.** 32,557 of 33,283
   `fundamental_scores` rows carry an `as_of` earlier than the first capture, so
   no historical policy can reproduce them. They stay correctly labelled
   `current_vintage`.

**Replayable fundamental history begins 2026-08-16, not 1998.** True before this
work and invisible; now measured.

### What this implies for M1

The binding constraint is narrower than M1 as originally scoped. Canonical
multi-source evidence, typed provenance and entity governance are all real work,
but none of them moves `true_pit` off zero — and while it is zero, M3 (corrected
research) cannot start at all, because every leak-free replay returns empty.

The child plan `docs/superpowers/plans/2026-08-24-m1-publication-evidence.md`
therefore leads with a publication-evidence adapter and defers the rest of M1
behind it. Rationale and measurements are in the research artifact.

### Still not done

No commit, push, PR, or image deploy. The branch remains
`feat/fundamental-pm-research-system` at baseline `86161f1d` plus uncommitted work.
Migrations 130/131 ARE live on production (additive only, backward compatible with
the currently deployed image, which ignores both).
