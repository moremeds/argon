# Release runbook

Argon ships to the Mac mini through immutable GHCR images and the engine-wide
Watchtower. The launchd application stack and deploy poller were retired on
2026-07-08; `docs/runbooks/docker-deploy.md` is the production topology and
rollback authority.

## Cut a release

1. Land every feature PR on `main`, including its `CHANGELOG.md` entry under
   `## [Unreleased]`.
2. From a clean, current local `main`, run
   `scripts/release/cut.sh prepare [patch|minor|major]`. It opens a
   `release/vX.Y.Z` PR that updates `VERSION`, `pyproject.toml`,
   `web/package.json`, `uv.lock`, and CHANGELOG together.
3. Merge the release PR. Its merge commit starts the complete main-push CI suite:
   Python static/unit, all four duration-balanced integration shards, web
   typecheck/unit/lint/build, and the technicals Playwright regression.
4. Return local `main` to the exact `origin/main` merge commit and run
   `scripts/release/cut.sh tag`. The command waits for that exact SHA's successful
   `push` run of `ci.yml` before creating or pushing the tag. Do not cut another
   tag while a Release workflow is running or queued.

The tag fires `.github/workflows/release.yml` in this order:

1. **verify tagged commit provenance** — require the tag commit to be on `main`,
   require the exact-SHA successful main CI run again (manual-tag defense), check
   strict SemVer/tag/VERSION agreement, require that the tag's base version is still
   the current `origin/main:VERSION`, and require a non-empty matching CHANGELOG
   section. This rejects historical tag reruns that could roll `:latest` backward.
   It does not rerun a second, potentially drifting test subset.
2. **require new version tags** — fail closed unless neither image already has the
   requested `:X.Y.Z` (or prerelease) tag. Version tags are never overwritten by a
   workflow rerun.
3. **build immutable images** — build `argon-app` and `argon-web` natively for
   arm64 and push only the new version tags. Both matrix legs upload their exact
   build-produced manifest digest.
4. **promote final latest tags** — finals only. Require both version tags to resolve
   to those build-produced digests, preflight both prior `:latest` digests, then
   retag the complete pair. A mid-promotion failure attempts to restore every
   touched image to its previous digest. Prereleases skip this step completely.
5. **publish GitHub Release** — runs last, after both immutable builds and, for a
   final, successful promotion. Release notes come from the matching CHANGELOG
   section.

Do not rerun an already-tagged Release workflow. If a matrix leg fails after the
other version image was published, preserve the partial tag as evidence and cut a
new patch version after diagnosing the failure. Deleting or replacing a version tag
requires an explicit incident decision; it is not an ordinary retry path.

Cross-package tag updates are not a registry transaction. Preflight and rollback
prevent the former persistent one-build-passed/one-build-failed state, but an
observer can still see a short interval between the two successful retags.

## Deployment boundary

For a final release, Watchtower notices the new `:latest` images and asynchronously
recreates the enabled Argon services from `/opt/argon/compose.yml`. GitHub Actions
cannot reach the private mini and therefore does **not** prove deployment success.
A green Release workflow means artifacts are published, not that production has
converged.

After Watchtower runs, verify on the mini:

```bash
curl -s http://127.0.0.1:8400/api/health | jq '{version, db, active: .ws_consumer.active_source}'
for p in / /gold /regime /stock/AAPL; do
  curl -sfo /dev/null -w "%{http_code} $p\n" "http://127.0.0.1:3001$p"
done
curl -s http://127.0.0.1:3001/api/health | jq '{via_web_rewrite: .db, version}'
```

Required observations:

- API `version` equals the released tag and `db == "up"`.
- The expected live source is visible (normally `xenon_ws`).
- SSR routes return 200.
- The web `/api/*` rewrite returns API JSON, not an HTML/500 response.

Watchtower notifications use xenon's shared ntfy deployment topic. They are useful
evidence that an update was attempted, but the health checks above are the deploy
acceptance gate.

## Migrations

The `api` container is the single routine migration owner:

```text
python -m uw_scan.storage.migrate_runner && exec uvicorn ...
```

It cannot serve new code until idempotent migrations succeed. Workers may recreate
before the API because Watchtower ignores Compose ordering; their scheduled jobs are
exception-safe. A migration that must precede all new code still requires the
explicit out-of-band path before release:

```bash
cd /opt/argon
docker-compose --profile migrate run --rm migrator
```

## Rollback

Watchtower has no health-gated rollback. Pin both images to the same previous
immutable version in `/opt/argon/compose.yml`, then recreate:

```bash
cd /opt/argon
# edit argon-app and argon-web from :latest to the same known-good :X.Y.Z
docker-compose up -d
```

Confirm API version, DB health, SSR, and web rewrite again. Do not roll back only one
image unless the incident analysis explicitly proves the cross-version contract is
compatible.

## Historical note

`scripts/deploy/macmini-deploy-poller.sh`, `scripts/deploy/macmini-prod.sh`, and the
launchd plist template remain as historical rollback evidence. They are not the
active release or deployment path and must not be restarted alongside Docker.
