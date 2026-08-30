# Fast, Coverage-Preserving Release Design

**Date:** 2026-08-30

**Goal:** Reduce tag-to-image release latency without removing, combining, skipping,
or shortening any test, while making the tag, image, and GitHub Release sequence
safer for the Docker + Watchtower production path.

## Constraints

- The exact tagged SHA must have a successful `push` run of `.github/workflows/ci.yml`
  on `main`. PR-only CI is not sufficient.
- Release automation reuses that immutable CI result; it does not rerun a weaker or
  differently configured subset.
- Existing unit, integration, web, and browser tests remain collected and executed
  by CI. Test-speed work may change algorithms or fixture transport only when output
  parity is covered by tests.
- Prereleases publish immutable image tags and a GitHub prerelease, but never move
  `:latest`.
- Final releases build both immutable images before either `:latest` tag moves.
- A release tag must be strict SemVer for the current `origin/main:VERSION`;
  historical tag reruns cannot move production backward.
- Existing immutable version tags are never overwritten, and promotion consumes the
  exact digests emitted by the current build jobs.
- A GitHub Release is published only after all required image work succeeds.
- No commit, push, PR, or production mutation is part of this implementation without
  separate user approval.

## Architecture

### Same-SHA CI gate

Add a stdlib-only helper that queries GitHub Actions through the authenticated `gh`
CLI. It accepts repository, SHA, workflow, branch, and wait settings; it succeeds
only when an exact-SHA `push` run on `main` is complete and successful. `cut.sh tag`
waits on this gate before creating the tag. The tag workflow repeats the same check
as defense in depth for manually pushed tags.

The release `verify` job keeps only release-specific checks: main ancestry,
tag/VERSION agreement, committed version consistency, release classification, and
non-empty CHANGELOG extraction. The full CI suite continues to run once, unchanged,
on the same commit.

### Image build, promotion, and publication

An image preflight fails closed if either requested `:<version>` tag already exists.
The arm64 matrix then builds and pushes only new immutable version tags and records
the exact digest emitted by each build. A later final-release job requires the two
version tags to resolve to those digests before promoting them to `:latest`.
Promotion records the previous `latest` digests and attempts rollback if either
retag fails.
Cross-package registry updates cannot be truly transactional, but preflight plus
rollback removes the current persistent one-image-success/one-image-failure state.

The GitHub Release job waits for immutable builds and, for finals, successful
promotion. Prereleases skip promotion but still wait for both immutable builds.
Workflow-level release concurrency prevents two running tags from racing the shared
`:latest` names. GitHub permits only one pending run per concurrency group, so the
documented cutter remains intentionally sequential: do not cut another tag while a
release is running or queued.

### Coverage-preserving integration acceleration

No tests are deleted, merged, deselected, or given shorter data windows. Two bounded
optimizations are permitted:

1. Replace pairwise O(P*N) AUC calculation with an exactly tie-preserving rank/group
   algorithm, reducing complexity to O(N log N). Exhaustive/reference equivalence
   tests and a comparison-count regression guard prove behavior and complexity.
2. Replace per-row seed INSERT round trips in the canary integration fixture with a
   temporary-table COPY followed by the same `ON CONFLICT DO NOTHING` insert. A real
   Postgres integration test proves row/value and idempotency parity.

The complete integration suite is executed with `--store-durations` to produce a
candidate scheduling manifest, but scheduling data is accepted only when captured
under CI-compatible concurrency. A ten-worker unsharded local capture folded
Postgres lock/checkpoint waits into five apparent 251-376 second test costs and made
the two-worker GitHub shards take 11:45 and 7:20. The committed manifest therefore
keeps the last GitHub-calibrated baseline and adds the new real-Postgres test's
measured duration. A unit guard rejects contention-poisoned entries above 60 seconds.
Coverage is proven independently by node-ID collection: every baseline node must
remain collected, and the fixture batching change adds one regression test.

## Failure handling

- Missing, failed, cancelled, or wrong-branch CI blocks tagging and release.
- A timeout reports the observed run state and exits non-zero.
- Missing immutable images block promotion before `:latest` changes.
- A malformed tag, a historical-version replay, an existing version image tag, or a
  mismatch between a version tag and its build-produced digest blocks the release.
- A mid-promotion error attempts to restore every already-promoted image to its
  captured prior digest and exits non-zero.
- GitHub Release publication cannot run after a failed build or failed final
  promotion.
- Watchtower remains asynchronous. The workflow and runbook must state that artifact
  publication is proven but live mini deployment is not, until a reachable mini
  runner or callback exists.

## Acceptance criteria

- Current Python unit, integration, web unit, typecheck, lint, build, and browser
  commands pass.
- All 1,658 integration tests from the v0.13.1 baseline remain collected, with one
  new real-Postgres batching regression test (1,659 total; zero removals).
- CI workflow still contains all four integration shards and `-n auto`.
- Release workflow contains no second pytest/npm test suite.
- Exact-SHA main push CI is required in both `cut.sh tag` and `release.yml`.
- Both immutable images precede final `:latest` promotion; GitHub Release is last.
- Prereleases never promote `:latest`.
- Release runs are serialized.
- Historical release replay and immutable-version-tag overwrite are rejected.
- Duration scheduling metadata passes the contention-poisoning guard; node-ID
  collection, not manifest membership, proves coverage preservation.
