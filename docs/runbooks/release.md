# Release runbook

Argon ships to the Mac mini via a tag-driven pipeline (no Docker; launchd stack).

> **Docker migration in progress.** A Docker deploy path (Colima + GHCR +
> Watchtower, matching xenon/apex) has landed as artifacts — Dockerfiles,
> `docker-compose.yml`, and the `ghcr-push` job in `release.yml`. **The launchd
> stack below is still the live prod path** until the phased cutover runs; see
> `docs/runbooks/docker-deploy.md` and
> `docs/superpowers/specs/2026-07-06-docker-migration-design.md`. Once cutover
> completes (Phase 3), the launchd sections here are superseded.

## Cut a release

1. Land your feature PRs to `main` with CHANGELOG entries under `## [Unreleased]`.
2. `scripts/release/cut.sh prepare [patch|minor|major]` — opens a `release/vX.Y.Z`
   PR that bumps `VERSION` + `pyproject.toml` + `web/package.json`, re-locks
   `uv.lock` (so its editable self-version tracks the bump), and promotes the
   `[Unreleased]` block to `[X.Y.Z]`.
3. Merge that PR after CI is green.
4. `scripts/release/cut.sh tag` (on `main`) — tags `vX.Y.Z` and pushes the tag.

The tag push fires `.github/workflows/release.yml`:
- **verify** re-runs the full suite (ruff, guardrails, unit + integration, web
  build, `version_sync_check`) on the tagged commit.
- **publish** cuts a GitHub Release from the matching CHANGELOG section.

## Auto-deploy (the mini)

`com.argon.deploy-poller` (launchd, every 120s) polls
`gh api repos/moremeds/argon/releases/latest`. When the latest published,
non-prerelease Release tag differs from `logs/deployed_tag.txt`, it runs
`scripts/deploy/macmini-prod.sh <tag>` (checkout → build → migrate → one-off
data seed → kickstart → health-check → auto-rollback). The seed step runs
`scripts/backfill/market_tide_sentiment_backfill.py --if-empty` (best-effort, no
UW budget) so the tide slope→forward-return backtest has full history the moment
the feature ships. `--if-empty` makes it a true one-off — it seeds only when
`market_tide_sentiment_daily` is empty, so later deploys are an instant no-op
(drop the flag to force a full recompute, e.g. after a formula change).
Prereleases (`vX.Y.Z-rc1`) verify + publish a
GitHub prerelease but are **never** auto-deployed.

Logs: `logs/deploy-poller.{out,err}.log`, `logs/deploy.log`.
State: `logs/deployed_tag.txt` (last good deploy), `logs/deploy-poller.failed_tag`
(a release whose deploy failed + rolled back — the poller skips it until a newer
release; clear it manually once fixed: `rm logs/deploy-poller.failed_tag`).

## Manual deploys — pause the poller first

The poller serializes its own ticks with `lockf`, but a hand-run
`macmini-prod.sh` does **not** take that lock — running one while the poller fires
could race two `git checkout`s on the same tree. Before any manual deploy, pause
the poller, then resume it after:

```bash
launchctl unload ~/Library/LaunchAgents/com.argon.deploy-poller.plist   # pause
scripts/deploy/macmini-prod.sh <tag>                                    # manual deploy
launchctl load   ~/Library/LaunchAgents/com.argon.deploy-poller.plist   # resume
```

## Roll back

The poller and `macmini-prod.sh` auto-roll-back on a failed health check. To
force a rollback to a known-good release, **pause the poller** (above), then run
on the mini: `scripts/deploy/macmini-prod.sh <previous-good-tag>` (it records that
tag as deployed; the poller then stays put until a newer Release is published).
Resume the poller when done.

## First-time / dirty-tree note

`web/next-env.d.ts` is untracked and the deploy uses `npm ci`, so the tree stays
clean across deploys. If the poller logs `ALERT: working tree dirty`, inspect
`git status` on the mini and resolve (e.g. `git checkout -- <file>`) — never
`git reset --hard`.

Historically the recurring cause was `uv.lock`: `cut.sh` bumped the version files
but never re-locked, so the committed lock's editable self-version lagged
`VERSION`. The first `uv run` on the mini rewrote that one line, the tree went
dirty, and the poller refused every deploy — silently pinning prod to the
last-deployed release. `cut.sh prepare` now runs `uv lock` and commits it, and
`version_sync_check` (run pre-`uv sync` in CI, so a stale committed lock can't be
auto-repaired and hidden) fails the build if the lock self-version ever drifts
from `VERSION` again. If you still see a dirty `uv.lock` on the mini, it means an
out-of-band `uv` invocation re-resolved deps — `git checkout -- uv.lock` and
investigate why the committed lock disagreed with the installed environment.
