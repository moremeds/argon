# Docker deploy runbook (Mac mini)

**Status:** artifacts shipped, cutover **not yet performed**. The live prod path
is still the launchd stack (`docs/runbooks/release.md`). This runbook is the
procedure for the phased cutover and for operating argon once it runs in Docker.
Design + rationale: `docs/superpowers/specs/2026-07-06-docker-migration-design.md`.

## What this migration does

Moves the argon prod stack off launchd into Docker on the mini, matching the
xenon/apex house pattern: Colima VM, bridge network + `host.docker.internal`,
host-native Postgres (unchanged), GHCR images built by `release.yml`, and the
**single engine-wide Watchtower** in `/opt/xenon/compose.yml` for auto-deploy.
AI Codex/Claude workers are dropped in phase 1 (issue #248); DeepSeek survives.

## Images

Two images, built + pushed by the `ghcr-push` job in `release.yml` on every tag
(native `ubuntu-24.04-arm`, no QEMU):

- `ghcr.io/moremeds/argon-app` — api / workers / ws-consumer / migrator (one
  Python image; each service overrides `command:`). `.venv` on PATH → no
  `uv run` in-container.
- `ghcr.io/moremeds/argon-web` — Next.js 16 standalone.

`:X.Y.Z` is always published; `:latest` floats only for final releases
(prerelease tags with a hyphen are excluded, so Watchtower never auto-deploys an
rc). Local build smoke: `docker-compose build` (or per-image
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
Code + Dockerfiles + compose + `ghcr-push` merged; images published on the first
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
```

### Phase 3 — retire
After ~3 clean days, remove the app plists from `~/Library/LaunchAgents` (keep
the two `com.argon.backup*` plists — they stay host-native). Mark release.md
launchd sections superseded then.

## Rollback (any point)

```bash
cd /opt/argon && docker-compose down
for l in api web massive-ws worker-uw-0 ...; do launchctl bootstrap "gui/$(id -u)" \
  ~/Library/LaunchAgents/com.argon.$l.plist; done
```
The plists stay on disk through phase 2, and Postgres never moved, so the launchd
stack resumes from the same DB. Watchtower has **no** rollback for a bad image —
pin the previous tag: `sed -i '' 's#:latest#:X.Y.Z#' /opt/argon/compose.yml &&
docker-compose up -d`.

## Operating notes

- **Watchtower alerts route to xenon's ntfy topic** (`ntfy.sh/xenon-deploy-…`,
  titled "Xenon auto-deploy") — argon container updates show up there, branded as
  xenon. One shared deploy channel for the mini; expected, not a bug.
- **Env rotation** still needs a recreate: `docker-compose up -d --force-recreate
  <svc>` (same freeze-at-fork semantics as the launchd workers).
- **Schema changes**: `docker-compose --profile migrate run --rm migrator`. App
  services never self-migrate, so `up -d` is safe against the live schema.
- **Backups** (`com.argon.backup*`) remain host-native launchd — untouched by
  this migration.
