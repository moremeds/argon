# Argon release procedure — xenon-parity, launchd-native

**Date:** 2026-06-17
**Status:** Design approved, awaiting spec review → implementation plan
**Author:** chenxi

## Problem

Argon ships to the Mac mini (`100.66.147.98`) entirely by hand. There is no
release workflow, no `VERSION` file, no `CHANGELOG.md`, and zero git tags. A
human SSHes into the mini and runs `scripts/deploy/macmini-prod.sh vX.Y.Z`,
which already does the full deploy (checkout tag → build → migrate → kickstart
launchd → health-check → auto-rollback) — but nothing *triggers* it.

Xenon, by contrast, has a complete tag-driven release pipeline:
`release.yml` on a `v*` tag push runs tests, cuts a GitHub Release from the
`CHANGELOG`, builds four Docker images, and pushes them to GHCR; the mini's
**Watchtower** then auto-pulls `:latest` and restarts via docker-compose.

We want argon to have the **same automation shape** — *merge to main → cut a
release tag → a workflow fires only when a new version exists → the mini
rebuilds and restarts itself* — **without** adopting Docker.

## Why not Docker (the rejected path)

Full xenon parity would mean dockerizing all 13 `com.argon.*` launchd services.
This is rejected because:

- **AI-runner keychain auth is incompatible with Linux containers.** The
  `ai-codex` and `ai-claude` workers run local CLI subprocesses
  (`claude --print`, `codex exec`) that read **macOS keychain OAuth** and
  deliberately avoid `ANTHROPIC_API_KEY` (the env allow-list strips it so
  subscription auth wins). These cannot run inside a Linux container as-is.
- **`macmini-prod.sh` already is the deploy unit.** It performs the exact
  equivalent of "Watchtower pulls + docker-compose up" (checkout → build →
  migrate → restart → health-check → rollback). The only missing pieces are the
  *front half* (a release workflow) and a *trigger* (a poller). Rebuilding the
  deploy as containers would be net-negative work.

**Decision:** keep launchd. Add the release workflow + versioning discipline +
a pull-based poller that calls the existing `macmini-prod.sh`.

## End-to-end flow

```
Dev:     scripts/release/cut.sh prepare [patch|minor|major]
              → release/vX.Y.Z branch: bump VERSION+pyproject+web/package.json,
                promote CHANGELOG [Unreleased]→[X.Y.Z], push branch, open PR
         → merge the PR to main (CI green)            (never a direct push to main)
         → scripts/release/cut.sh tag                 (on main: tag the merged commit, push the TAG only)
GitHub:  push tag v*  →  .github/workflows/release.yml
            verify  : re-run pytest (sharded) + web build + version_sync_check on the tagged SHA
            publish : extract CHANGELOG[X.Y.Z] → softprops/action-gh-release
                      (prerelease=true if the tag has a -suffix, e.g. v0.2.0-rc1)
Mac mini: com.argon.deploy-poller  (launchd, StartInterval ~120s)
            → gh api repos/moremeds/argon/releases/latest → tag T (the latest *published*,
              non-prerelease Release; 404 = no release yet → no-op)
            → if T ≠ last-deployed:  /usr/bin/lockf -t 0 → bash scripts/deploy/macmini-prod.sh T
                 (existing script: checkout → build → migrate → kickstart → health → rollback)
            → on success, macmini-prod.sh records T in logs/deployed_tag.txt
```

Pull-based, like Watchtower: no inbound access to the mini, the mini decides
when to update, and re-runs every 120s via launchd `StartInterval` (+ `RunAtLoad`
so it also fires at boot).

**Verified on the mini (`moremeds@100.66.147.98`, macOS 26.5.1) 2026-06-17:**

- **No `flock`** — macOS ships `/usr/bin/lockf` and `/usr/bin/shlock` instead.
  The poller uses `/usr/bin/lockf -t 0 <lockfile> <cmd>` (non-blocking; fails
  immediately if a deploy is already running). `gtimeout` (coreutils) is present
  to bound `gh` calls.
- **`gh` 2.92.0 is installed and authenticated** as `moremeds`. The poller gates
  on `gh api .../releases/latest`, which returns **only the latest published,
  non-prerelease, non-draft Release**. This is strictly better than polling raw
  `git ls-remote` tags: the GitHub Release is created in `release.yml`'s
  `publish` job *after* `verify` passes, so the mini deploys **only verified
  releases** and never races the workflow. Prerelease exclusion is free (the API
  omits them). On `gh` failure / network error the poller **logs and skips**
  (never falls back to raw tags — skipping is safer than deploying unverified).
- **The mini working tree is currently DIRTY** (`web/next-env.d.ts`,
  `web/package-lock.json` — both build-generated). `macmini-prod.sh` *dies* on a
  dirty tree, so this is fixed at the root in **Component 0** before the poller
  can ever succeed.

## Components

### 0. Tree-cleanliness prerequisite (required before the poller can work)

The mini self-dirties its tree on every deploy, which blocks the next deploy's
dirty-guard. Two build-generated files are the cause; fix both at the root:

- **`web/next-env.d.ts`** — Next.js regenerates this on every `build`; Next's own
  `.gitignore` template excludes it. **Untrack it**: `git rm --cached
  web/next-env.d.ts` and add it to `web/.gitignore`. (It is recreated by the
  build, so nothing breaks.)
- **`web/package-lock.json` drift** — caused by `macmini-prod.sh` running
  `npm install`. **Switch the deploy to `npm ci`** in `macmini-prod.sh` (and
  `macmini-deploy-branch.sh`, which shares the checkout): `npm ci` is
  reproducible and never rewrites the lock. `ci.yml`'s web job already uses
  `npm ci` against the committed lock, so it is proven to install cleanly.
- **One-time mini cleanup** (in the deploy runbook / first execution): discard
  the current churn (`git checkout -- web/next-env.d.ts web/package-lock.json`)
  and pull the gitignore change so the first poller run starts from a clean tree.

After Component 0, the tree stays clean across deploys, so the poller's
dirty-guard (Component 4) only ever fires on a genuine anomaly.

### 1. Versioning artifacts (full xenon mirror)

- **`VERSION`** at repo root — single source of truth, e.g. `0.2.0`. Seeded at
  the current `0.1.0`.
- **`CHANGELOG.md`** — Keep-a-Changelog format: an `## [Unreleased]` block plus
  `## [X.Y.Z] — YYYY-MM-DD` sections with `### Added/Fixed/Changed`. Seeded with
  a `[0.1.0]` baseline entry summarizing the system as it stands.
- **Version lockstep** — `pyproject.toml [project].version` and
  `web/package.json` `"version"` must equal `VERSION`. Argon has **no root
  `package.json`** (all Node deps live under `web/`), so `web/package.json`
  (`name: uw-watchlist-web`, currently `version: 0.1.0`) is the only tracked
  Node package.
- **Runtime version wiring** — `src/uw_scan/api/server.py:29` currently
  hardcodes `FastAPI(title="UW Watchlist API", version="0.1.0")`. Wire it to read
  the root `VERSION` file (fallback to `"0.0.0+unknown"` if absent) so
  `/api/health` and the OpenAPI doc report the live release. This also lets the
  health probe in `macmini-prod.sh` / the poller confirm *which* version is live.

### 2. `scripts/release/` (ported from xenon, argon-adapted)

- **`_lib.sh`** — sourced, not executed. Ports two helpers verbatim from
  `xenon/scripts/release/_lib.sh` (both are repo-agnostic):
  - `bump_semver <version> <patch|minor|major>`
  - `extract_changelog_section <file> <version>` (awk-based; anchors on
    `^## \[` so in-body `## [` inside code fences can't terminate a section early).
- **`version_sync_check.py`** — adapted from xenon's. Asserts
  `VERSION == pyproject.toml [project].version == web/package.json.version`.
  `VERSION` is the source of truth. Exits non-zero with a per-file mismatch
  report. Runs in **both** `ci.yml` (catch drift on every PR) and `release.yml`
  (block a mistagged release before any GitHub Release is cut).
- **`cut.sh`** — two subcommands, split so the version bump lands via a **PR**
  and the tag is cut from an already-green `main` commit. This respects argon's
  firm rule: **`git push origin main` is forbidden; always open a PR.**
  - **`cut.sh prepare [patch|minor|major]`** (run from `main`, clean tree):
    1. Compute the new version via `bump_semver`.
    2. Create branch `release/vX.Y.Z`.
    3. Rewrite `VERSION`, `pyproject.toml` version, `web/package.json` version.
    4. Promote the `## [Unreleased]` CHANGELOG block to `## [X.Y.Z] — <today>`
       and re-seed an empty `## [Unreleased]`.
    5. Run `version_sync_check.py` locally to self-verify.
    6. Commit (`release: vX.Y.Z`), push the **branch**, open a PR via
       `gh pr create`. **Never pushes `main`, never tags here.** A human merges
       the PR after CI is green.
  - **`cut.sh tag`** (run from `main` after the release PR has merged):
    1. Refuse unless on `main`, clean tree, up to date with `origin/main`.
    2. Read `VERSION`; refuse if `version_sync_check.py` fails or the tag
       `v$VERSION` already exists.
    3. `git tag vX.Y.Z` on the merged commit, `git push origin vX.Y.Z`
       (**tag only**). The tag push is what fires `release.yml`.
  - Mirrors `xenon/scripts/release/cut.sh` ergonomics, adapted to argon's files
    and its PR-only-to-main policy (xenon's cut is single-phase; argon's is split).

### 3. `.github/workflows/release.yml`

- **Trigger:** `on: push: tags: ["v*"]`. Never fires on branch/PR push.
- **`verify` job** — Postgres service (`postgres:15`, matching `ci.yml`) + the
  same gates `ci.yml` runs:
  - `uv sync --extra postgres`, `ruff check src/ tests/ scripts/`,
    `scripts/_lint_except.py`, the guardrail greps, `check_migration_prefixes.py`,
    unit tests, and the 4-shard integration tests (against
    `option_wizard_local` / `option_wizard_test`, per the DB-isolation tripwire).
  - web: `npm ci`, `typecheck`, `test`, `lint`, `build`.
  - **plus** `scripts/release/version_sync_check.py`.
  - Rationale: the release proves itself green on the tagged SHA independently of
    when CI last ran. (Future DRY option: extract the test steps into a
    `workflow_call` reusable workflow shared by `ci.yml` and `release.yml`. Out of
    scope for v1.)
- **`publish` job** (`needs: verify`, `permissions: contents: write`):
  - Extract the CHANGELOG section for `${GITHUB_REF_NAME#v}` via
    `extract_changelog_section`.
  - Classify prerelease: a tag whose version contains `-` (e.g. `v0.2.0-rc1`) is
    a prerelease.
  - `softprops/action-gh-release@v3` with `body` = the changelog section,
    `prerelease` = the classification, `make_latest` only for final releases.
- **No GHCR/Docker job.** Xenon's `ghcr-push` has no analog; the poller +
  `macmini-prod.sh` replace Watchtower + image pull.

### 4. Mini deploy poller (the Watchtower-equivalent)

- **`scripts/deploy/macmini-deploy-poller.sh`**:
  - `T = gh api repos/moremeds/argon/releases/latest --jq .tag_name`, wrapped in
    `gtimeout 30`. HTTP **404 = no published release yet → clean no-op** (exit 0).
    Any other `gh`/network failure → log and skip (do **not** deploy).
  - Read last-deployed from `logs/deployed_tag.txt`; read the failed-attempt
    marker `logs/deploy-poller.failed_tag`.
  - **Dirty-tree guard:** if the tree is dirty, log + alert and **skip** — never
    `git reset --hard`/`checkout -f` (CLAUDE.md bans the destructive anti-pattern).
    After Component 0 the tree stays clean, so this only fires on a real anomaly.
  - If `T` ≠ last-deployed **and** `T` ≠ failed marker:
    `/usr/bin/lockf -t 0 logs/deploy-poller.lock bash scripts/deploy/macmini-prod.sh "$T"`
    (non-blocking lock; a still-running deploy makes the next 120s tick a no-op).
  - On `macmini-prod.sh` success → it has already written `logs/deployed_tag.txt`;
    poller clears the failed marker.
  - On failure (`macmini-prod.sh` self-rolled-back and exited non-zero) → poller
    writes `T` to the failed marker so it won't retry the same broken tag; logs
    loudly and waits for a newer tag (human intervenes).
  - Flags: `--once` (single pass, for testing/cron), `--dry-run` (print the
    decision, deploy nothing).
- **`config/templates/com.argon.deploy-poller.plist.template`** — launchd agent
  driven by `StartInterval=120` + `RunAtLoad` (NOT `KeepAlive`: that is for
  long-running daemons and would busy-loop a short-lived periodic script;
  `StartInterval` re-runs it every 120s). `StandardOutPath`/`StandardErrorPath` →
  `logs/deploy-poller.{out,err}.log`; `PATH` includes
  `/opt/homebrew/bin:/opt/homebrew/opt/postgresql@17/bin:…` (the `postgresql@17`
  bin is required — the deploy shells out to `psql` via `migrate.sh`; the generic
  templates omit it).
- **Bootstrap registration** — `scripts/deploy/macmini-bootstrap.sh` renders it
  via `render_static_plist "com.argon.deploy-poller"` and loads it **explicitly**
  (like `com.argon.backup`), **NOT** via `config/services.list`. The poller is the
  thing that *performs* deploys; it must never be kickstarted as part of an app
  deploy. This mirrors the existing backup-plist exclusion exactly.

### 5. `macmini-prod.sh` (two changes)

Already does checkout → build → migrate → kickstart → health-check → rollback.

- **Fix the health-check path (load-bearing).** It probes
  `http://127.0.0.1:8400/health`, which returns **404** — the health router is
  mounted under `prefix="/api"`, so the real path is `/api/health` (verified 200
  on the live mini 2026-06-17). The mini is healthy today only because its last
  deploy went through `macmini-deploy-branch.sh` (which probes `/api/health`
  correctly). The first **poller-driven** `macmini-prod.sh` deploy would 404 →
  fail health → auto-rollback → poller marks the tag failed → the release never
  ships. Fix both occurrences (primary + rollback check) to `/api/health`.
- **Record the deployed tag.** On a successful deploy, write the tag to
  `logs/deployed_tag.txt` (authoritative state the poller reads). On rollback the
  file is **not** advanced (it still reflects the last good release).

The existing rollback path and `logs/deploy.log` audit line are otherwise
untouched.

## Failure handling

- **Prerelease tags never auto-deploy.** `gh api .../releases/latest` omits
  prereleases/drafts, so `v0.2.0-rc1` verifies + publishes a GitHub prerelease
  but the mini ignores it. Mirrors xenon's `:latest` gating, for free.
- **Only verified releases deploy.** The poller gates on the *published Release*,
  which `release.yml` creates only after `verify` passes — the mini never sees a
  tag whose verification is still running or failed.
- **No retry storms.** A failed deploy records the attempted tag in a failed
  marker; the poller skips it until a newer tag appears.
- **No overlap.** `flock` guards against a slow build being re-entered by the
  next 120s tick.
- **No double-deploy with a human.** The poller and a manual `macmini-prod.sh`
  contend on the same `flock`; whichever holds the lock wins, the other waits/skips.
- **Mistagged commit can't ship.** `version_sync_check` in `verify` fails the
  release before any GitHub Release is cut. `verify` additionally asserts the tag
  matches `VERSION` (allowing a `-prerelease` suffix), so a hand-pushed tag like
  `v0.5.0` on a `VERSION=0.1.0` commit is rejected before publish/deploy.

## Testing

- **`version_sync_check`** — pytest: matching versions pass; a deliberately
  drifted `web/package.json` / `pyproject` fails with the right message.
- **`extract_changelog_section`** — shell test: middle section, last section,
  and missing-version cases.
- **Poller logic** — exercise `macmini-deploy-poller.sh --dry-run --once`
  against a stub tag list / temp `deployed_tag.txt`: confirm it picks the highest
  non-prerelease tag, ignores prereleases, and no-ops when already current.
- **First live validation** — cut `v0.2.0-rc1` first: it must verify + publish a
  GitHub **prerelease** and the mini must **not** deploy it. Then cut `v0.2.0`:
  verify + final Release + the poller deploys within ~2 min and health passes.

## Docs

- **`CLAUDE.md`** — add a "Release procedure" section (cut → workflow → poller →
  rollback) and reference `scripts/release/` + the poller in "Where to look first".
- **`AGENTS.md`** — keep in sync (root Codex file mirrors policy per project rule).
- **Runbook** — `docs/runbooks/release.md`: how to cut a release, how the poller
  works, how to roll back (re-tag a prior version or manually
  `macmini-prod.sh <prev-tag>`), how to clear a failed marker.
- **Memory** — update the "Mac mini deploy gotchas" note to record the new
  automated path (poller) alongside the manual SSH sequence.

## Out of scope (v1)

- Dockerization / GHCR (rejected above).
- A `workflow_call` reusable workflow to de-dupe test steps between `ci.yml` and
  `release.yml` (noted as a future cleanup).
- Frontend independent versioning (`web/package.json` versions in lockstep with
  `VERSION` for now).
- Slack/Discord release notifications.

## Resolved during pre-planning mini inspection (2026-06-17)

- ✅ Mini git creds: `osxkeychain` helper, `gh` authed as `moremeds` — release
  polling and tag fetch work non-interactively.
- ✅ `flock` absent → use `/usr/bin/lockf -t 0` (verified present).
- ✅ `gh` present/authed → poller gates on `gh api .../releases/latest`
  (404-when-empty handled as no-op).
- ✅ Dirty-tree root cause identified (`web/next-env.d.ts`,
  `web/package-lock.json`) → Component 0.
- ✅ launchd layout confirmed: `com.argon.backup` is rendered + loaded but kept
  out of `services.list`; the poller follows that exact pattern.

## Open items to confirm during implementation

- Pin `softprops/action-gh-release` to whatever major xenon currently uses
  (xenon pins `@v3`).
- Decide the seeded `[0.1.0]` CHANGELOG body (one-paragraph baseline vs. a fuller
  retro of shipped features).
