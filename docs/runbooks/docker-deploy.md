# Docker deploy runbook (Mac mini)

**Status:** **cutover complete — argon runs in Docker on the mini as of 2026-07-08.**
The launchd app stack is retired (its 14 plists moved to
`/opt/argon/retired-launchd-plists/`; only `com.argon.backup` stays host-native).
This runbook remains the operating procedure and the rollback reference. Design +
rationale: `docs/superpowers/specs/2026-07-06-docker-migration-design.md`.

## What this migration does

Moves the argon prod stack off launchd into Docker on the mini, matching the
xenon/apex house pattern: Colima VM, bridge network + `host.docker.internal`,
host-native Postgres (unchanged), GHCR images built by `release.yml`, and the
**single engine-wide Watchtower** in `/opt/xenon/compose.yml` for auto-deploy.
AI Codex/Claude workers are dropped in phase 1 (issue #248); DeepSeek survives.

## Images

Two images, built + pushed by the `build-images` matrix in `release.yml` on every
tag (native `ubuntu-24.04-arm`, no QEMU):

- `ghcr.io/moremeds/argon-app` — api / workers / ws-consumer / migrator (one
  Python image; each service overrides `command:`). `.venv` on PATH → no
  `uv run` in-container.
- `ghcr.io/moremeds/argon-web` — Next.js 16 standalone.

Before either build, the workflow requires both requested `:X.Y.Z` tags to be absent;
an existing version tag is never overwritten by a rerun. Each matrix leg records its
build-produced digest. A final release requires the complete version pair to resolve
to those exact digests, then a separate promotion job moves both `:latest` tags; if
a retag fails, it attempts to restore every touched image's previous digest. The
GitHub Release is published only after that succeeds. Historical release tags are
rejected once `origin/main:VERSION` advances. Prerelease tags with a hyphen skip
promotion, so Watchtower never auto-deploys an rc. Local build smoke:
`docker-compose build` (or per-image
`docker build -f docker/app.Dockerfile -t argon-app:dev .`).

## Compose topology

`docker-compose.yml` at the repo root is the source of truth, mirrored to the
mini's `/opt/argon/compose.yml`. 10 services (9 long-running + a profile-gated
one-shot `migrator`). Every app service carries
`com.centurylinklabs.watchtower.enable: "true"`, `extra_hosts:
["host.docker.internal:host-gateway"]`, and `env_file: [/opt/argon/.env]`.

## `/opt/argon/.env` — key remaps from the launchd `.env`

| Var | container value |
|---|---|
| `UW_SCAN_DB_HOST` | `host.docker.internal` |
| `UW_SCAN_DB_NAME` | `option_wizard` |
| `XENON_WS_URL` | `ws://host.docker.internal:8765` |
| `XENON_WS_PORT_FILE` | `""` (empty — host-local file, invisible in-container) |
| `XENON_QUERY_API_URL` | `http://host.docker.internal:8321` |
| `APEX_API_URL` | `http://host.docker.internal:8322` |
| `TRADE_INSIGHTS_AI_ENABLED` / `..._CLAUDE_ENABLED` | `false` (Codex/Claude off) |
| `TRADE_INSIGHTS_AI_DEEPSEEK_ENABLED` | `true` |

**Do NOT set `UW_SCAN_ALLOW_DB_MISMATCH=1`** in the container `.env` — it bypasses
ALL DB-isolation checks. The clean container path is the legal
`host.docker.internal` + `option_wizard` pair (allowed by `_HOST_DB_RULES`), no
override. `NEXT_INTERNAL_API_BASE=http://api:8400` is set in compose, not `.env`
(it drives both the client `/api/*` rewrite and SSR fetches).

## Cutover — phased, reversible

### Phase 0 — prep (done in this PR)
Code + Dockerfiles + compose + GHCR build jobs merged; images published on the first
tag after merge. Local smoke on the MacBook against `option_wizard_local`.

### Phase 1 — mini setup (no cutover yet)

> **⚠ The Colima resize bounces the WHOLE mini, not just argon.** One shared
> Colima VM hosts xenon (live IB feed), apex, and the trading-observability
> stack. Schedule this in a **market-closed window**. After restart, verify all
> three return healthy before touching argon.

```bash
ssh macmini
export PATH=/opt/homebrew/bin:$PATH
colima stop && colima start --cpu 6 --memory 8      # required headroom (~2 GiB for argon)
# verify neighbours are back:
docker ps                                            # xenon-*, apex-*, trading-* all Up
docker login ghcr.io                                 # same PAT as xenon
# create /opt/argon/{compose.yml,.env}  (mirror repo compose.yml; author .env per table above)
docker-compose --profile migrate run --rm migrator   # idempotent; safe against the live DB
# do NOT start app services yet
```

### Phase 2 — cutover (the double-writer moment)

```bash
# 1. Fully stop the launchd app stack FIRST (running both double-writes + double-burns UW budget):
for l in api web massive-ws worker-uw-0 worker-uw-1 worker-massive-0 worker-massive-1 \
         worker-ai-deepseek-0 worker-ai-deepseek-1 deploy-poller; do
  launchctl bootout "gui/$(id -u)/com.argon.$l" 2>/dev/null || true
done
# 2. Start compose:
cd /opt/argon && docker-compose up -d
# 3. Verify SERVING LIVENESS (not .ok — it's routinely false under budget throttle):
curl -s http://127.0.0.1:8400/api/health | jq '{version, db, active: .ws_consumer.active_source}'
#   want: version == deployed tag, db == "up", active_source == "xenon_ws"
# 4. Verify SSR renders data (catches the NEXT_INTERNAL_API_BASE regression):
for p in / /gold /regime /stock/AAPL; do curl -sfo /dev/null -w "%{http_code} $p\n" http://127.0.0.1:3001$p; done
# 5. Verify the CLIENT-SIDE /api/* rewrite proxies web -> api. SSR page codes
#    (step 4) pass even when this is broken, so check it explicitly: the browser
#    hits web:3001/api/*, which next.config rewrites to the api service. The
#    rewrite target is BAKED at image build (ARG NEXT_INTERNAL_API_BASE in
#    web.Dockerfile); a mis-baked image 500s here while step 4 stays green.
curl -s http://127.0.0.1:3001/api/health | jq '{via_web_rewrite: .db, version}'
#   want: db == "up" (NOT a 500 / HTML error page)
```

### Phase 3 — retire (DONE 2026-07-08)
The 14 launchd app plists (api, web, massive-ws, the 10 workers, deploy-poller)
were moved out of `~/Library/LaunchAgents` into `/opt/argon/retired-launchd-plists/`
— moving them (not just `launchctl bootout`) is what stops `RunAtLoad` from
resurrecting them on reboot. Only `com.argon.backup` remains host-native (there
is **one** backup plist, not two). On reboot the containers return via Docker's
`restart: unless-stopped`, same as xenon/apex. Deploys now flow through the
engine-wide Watchtower (new `:latest` image → auto-recreate); the old launchd
`deploy-poller` + `macmini-prod.sh` files are historical only.

## Rollback (any point)

```bash
cd /opt/argon && docker-compose down
# Post-phase-3: move the retired plists back into the launchd scan dir first.
mv /opt/argon/retired-launchd-plists/com.argon.*.plist ~/Library/LaunchAgents/
for l in api web massive-ws worker-uw-0 ...; do launchctl bootstrap "gui/$(id -u)" \
  ~/Library/LaunchAgents/com.argon.$l.plist; done
```
The retired plists live in `/opt/argon/retired-launchd-plists/`, and Postgres never
moved, so the launchd stack resumes from the same DB. Watchtower has **no** rollback for a bad image —
pin the previous tag: `sed -i '' 's#:latest#:X.Y.Z#' /opt/argon/compose.yml &&
docker-compose up -d`.

## Operating notes

- **Watchtower alerts route to xenon's ntfy topic** (`ntfy.sh/xenon-deploy-…`,
  titled "Xenon auto-deploy") — argon container updates show up there, branded as
  xenon. One shared deploy channel for the mini; expected, not a bug.
- **GitHub Actions does not verify the live Watchtower result.** A green Release
  workflow proves exact-SHA CI, immutable image publication, final tag promotion,
  and GitHub Release publication. Confirm the mini separately with the health and
  SSR checks above; do not read "Release artifacts published" as a deploy ACK.
- **Env rotation** still needs a recreate: `docker-compose up -d --force-recreate
  <svc>` (same freeze-at-fork semantics as the launchd workers).
- **Schema changes auto-apply on deploy.** The `api` service self-migrates
  (`migrate_runner && exec uvicorn` in its `command`) before serving, so a
  Watchtower image update applies pending migrations automatically — closing the
  gap where Watchtower deploys new *code* but never runs the one-shot `migrator`
  (v0.10.0 shipped code against an un-migrated DB for ~7h). A bad migration
  crash-loops api (healthcheck red → `web` down), which is intentional: loud
  beats the silent partial-serving that hid the v0.10.0 gap. The `migrator`
  profile is still valid for **first-boot bootstrap** (before api exists) and
  explicit out-of-band applies: `docker-compose --profile migrate run --rm migrator`.
- **`compose.yml` changes are NOT auto-deployed** — Watchtower updates images
  only. After merging a change to the committed `docker-compose.yml` (e.g. this
  self-migrate command), mirror it to `/opt/argon/compose.yml` on the mini and
  `docker-compose up -d api` once to activate. Future image-only releases then
  self-migrate through the updated command.
- **Backups** (`com.argon.backup*`) remain host-native launchd — untouched by
  this migration.
