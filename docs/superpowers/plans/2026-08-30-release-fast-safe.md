# Fast, Coverage-Preserving Release Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make Argon releases reuse exact-SHA green CI, coordinate immutable image
builds before promotion/publication, and accelerate integration internals without
reducing test coverage.

**Architecture:** CI remains the single full-suite authority. A tested release helper
gates tags on the exact main-push SHA; release-specific checks then build immutable
arm64 images, promote finals with rollback, and publish last. Test internals receive
only behavior-equivalent AUC and Postgres seed batching optimizations.

**Tech Stack:** Python 3.13 stdlib, GitHub CLI/API, GitHub Actions, Docker Buildx,
pytest/xdist/pytest-split, psycopg 3, PostgreSQL 15, Vitest/Next.js.

---

### Task 1: Exact-SHA CI gate

**Files:**
- Create: `scripts/release/require_ci_success.py`
- Create: `tests/unit/test_release_ci_gate.py`
- Modify: `scripts/release/cut.sh`

1. Write unit tests for exact SHA/event/branch matching, success, active wait,
   terminal failure, missing run, timeout, and malformed `gh` output.
2. Run the focused tests and verify RED because the helper does not exist.
3. Implement the smallest stdlib helper around `gh run list` with injectable command,
   sleep, and clock functions.
4. Run the focused tests and verify GREEN.
5. Add the gate to `cut.sh tag` before tag creation and test shell syntax/text
   invariants.
6. Checkpoint the diff; do not commit without user approval.

### Task 2: Safe workflow graph

**Files:**
- Create: `tests/unit/test_release_workflow.py`
- Modify: `.github/workflows/release.yml`

1. Write workflow-structure tests asserting same-SHA gate permissions, no duplicate
   test commands, immutable-only matrix builds, final-only promotion, publish-last
   dependencies, prerelease behavior, and serialized concurrency.
2. Run the tests and verify RED against the existing workflow.
3. Replace the serial full-suite verify job with release-specific validation plus the
   exact-SHA CI gate.
4. Change matrix builds to immutable tags only.
5. Add final-only promotion and make publication depend on the correct final or
   prerelease path.
6. Parse the YAML and run actionlint when available; verify focused tests GREEN.
7. Checkpoint the diff; do not commit without user approval.

### Task 3: Promotion rollback helper

**Files:**
- Create: `scripts/release/promote_images.py`
- Create: `tests/unit/test_release_image_promotion.py`
- Modify: `.github/workflows/release.yml`

1. Write tests for preflight, two-image promotion, digest verification, failure before
   mutation, and rollback after partial mutation.
2. Run the tests and verify RED.
3. Implement digest inspection and retag commands using Docker Buildx with injectable
   command execution.
4. Run the tests and verify GREEN.
5. Wire the helper into the promotion job.
6. Checkpoint the diff; do not commit without user approval.

### Task 4: Tie-preserving O(N log N) AUC

**Files:**
- Modify: `scripts/backtest_canary.py`
- Create: `tests/unit/test_backtest_canary_auc.py`
- Existing regression: `tests/unit/test_within_band_aucs.py`

1. Write exhaustive/reference parity tests covering empty input, missing labels,
   all-one/all-zero labels, ties, duplicate scores, and random deterministic inputs.
2. Add a comparison-count test that fails the pairwise O(N^2) implementation.
3. Run and verify RED on the complexity guard.
4. Implement sorted equal-score grouping with exact half-credit tie semantics.
5. Run focused tests and existing within-band AUC tests; verify GREEN.
6. Benchmark old-reference versus new implementation without changing outputs.
7. Checkpoint the diff; do not commit without user approval.

### Task 5: Bulk canary history seeding

**Files:**
- Modify: `tests/integration/regime/_canary_v2a_fixture.py`
- Create: `tests/integration/regime/test_canary_v2a_fixture.py`

1. Write a real-Postgres test for expected rows/values and repeated-call idempotency.
2. Run it against the existing helper to establish behavior, then add an operation-
   count assertion that verifies RED on per-row INSERT behavior.
3. Implement temporary-table COPY plus `INSERT ... ON CONFLICT DO NOTHING`.
4. Run the focused integration test and all canary-v2 integration files; verify GREEN.
5. Compare before/after focused runtime.
6. Checkpoint the diff; do not commit without user approval.

### Task 6: Documentation and changelog

**Files:**
- Modify: `CLAUDE.md`
- Modify: `docs/runbooks/release.md`
- Modify: `docs/runbooks/docker-deploy.md`
- Modify: `scripts/release/cut.sh`
- Modify: `CHANGELOG.md`

1. Update the documented gate/build/promote/publish sequence.
2. Remove launchd-poller claims from the active release procedure and final cutter
   message.
3. State the Watchtower deployment-verification boundary explicitly.
4. Add the `[Unreleased]` changelog entry.
5. Run documentation/release invariant tests.

### Task 7: Duration manifest and full verification

**Files:**
- Modify mechanically: `.test_durations`

1. Record the v0.13.1 baseline integration node IDs; expected 1,658.
2. Run the complete integration suite with `-n auto --store-durations`; do not filter,
   deselect, shorten history, or exclude slow tests. Treat this as a candidate
   scheduling manifest, not coverage evidence.
3. Reject a candidate captured under mismatched concurrency if lock/checkpoint waits
   poison individual durations. Keep the last GitHub-calibrated baseline and add the
   new test's measured duration when that is the safer scheduler input.
4. Record post-change node IDs and require zero baseline removals; expect one added
   real-Postgres batching regression test (1,659 total).
5. Run the complete Python static/unit gate, four integration shard commands, web
   typecheck/test/lint/build, and technicals Playwright regression.
6. Validate YAML/actionlint, Docker promotion helper tests, shell syntax, and clean
   version synchronization.
7. Inspect the final diff for any test deletion, skip-marker addition, or coverage
   reduction.
8. Report results and residual deployment-verification limitation; do not commit,
   push, open a PR, or deploy without user approval.

### Task 8: Adversarial release hardening

**Files:**
- Create: `scripts/release/validate_release.py`
- Create: `tests/unit/test_release_validation.py`
- Modify: `scripts/release/promote_images.py`
- Modify: `tests/unit/test_release_image_promotion.py`
- Modify: `tests/unit/test_release_workflow.py`
- Modify: `.github/workflows/release.yml`

1. Reject non-SemVer and historical tags before privileged release work.
2. Fail closed if either immutable version tag already exists.
3. Upload both build-produced digests and require promotion to consume those exact
   digests.
4. Route tag-derived values through step environment variables rather than shell
   source interpolation.
5. Re-run release regression, workflow lint, and full project gates.
