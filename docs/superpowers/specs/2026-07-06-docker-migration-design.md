# Argon Docker migration — design

**Date:** 2026-07-06 · **Status:** DRAFT (design approved pending review)
**Goal:** move the argon prod stack off launchd into Docker on the Mac mini, matching the xenon/apex house pattern (Colima, bridge network + `host.docker.internal`, host-native Postgres, GHCR images from `release.yml`, Watchtower auto-deploy). AI analysis (Codex/Claude CLI) is knowingly sacrificed in phase 1 and rewritten later; DeepSeek survives.

## House pattern adopted (verified from xenon/apex)

- **Runtime:** Colima VM on the mini (brew service). xenon default profile is 2 CPU / 2 GiB — argon adds ~12 containers, so resize to `colima start --cpu 6 --memory 8` (xenon docs already flag OOM risk at 2 GiB with 4 containers).
- **Networking:** bridge, published ports, `extra_hosts: ["host.docker.internal:host-gateway"]` on every service. Never `127.0.0.1` for host resources ("127.0.0.1 is the container itself" — xenon runbook).
- **Postgres:** stays host-native Homebrew. Containers reach it at `host.docker.internal:5432`, DB `option_wizard`, role `argon_app`. No data moves.
- **Images:** built/pushed by `.github/workflows/release.yml` on `ubuntu-24.04-arm` (native arm64, no QEMU — apex pattern) to GHCR, tags `:X.Y.Z` + `:latest` (prereleases excluded from `:latest`).
- **Deploy:** apex-style — compose file mirrored at `/opt/argon/compose.yml`, app services carry `com.centurylinklabs.watchtower.enable: "true"`. The single engine-wide Watchtower already in `/opt/xenon/compose.yml` polls GHCR every 60s and recreates on new `:latest`. **Do not add a second Watchtower.** This preserves argon's current auto-deploy UX (deploy-poller retires).
- **Mini quirks:** hyphenated `docker-compose` (brew v5.1.3); SSH needs `PATH=/opt/homebrew/bin:$PATH`; Colima starts at user login only (auto-login tradeoff already accepted for xenon).

## Images (2, not 4 — deliberate simplification vs xenon)

xenon ships 4 near-identical Dockerfiles. Argon's api/workers/ws-consumer/migrator all run the same Python package, so:

1. **`ghcr.io/moremeds/argon-app`** — multi-stage `python:3.13-slim`; uv static binary (`COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/`), `uv sync --frozen --no-dev --extra postgres` in builder, runtime copies `.venv` + `src` + `scripts/` + `db` migrations, installs `libpq5 ca-certificates curl tini`; tini is PID 1. No default CMD dependence — each compose service sets `command:`.
2. **`ghcr.io/moremeds/argon-web`** — `node:22-alpine` multi-stage, Next.js **standalone output** (requires `output: 'standalone'` in `web/next.config.mjs`), `CMD ["node", "server.js"]`.

## Compose topology (`/opt/argon/compose.yml`)

| Service | command | ports | notes |
|---|---|---|---|
| `migrator` | `uv run bash scripts/migrate.sh` (in-process psycopg, no psql needed) | — | `profiles: ["migrate"]`, `restart: "no"` — never auto-runs on `up -d` (xenon pattern) |
| `api` | `uv run uvicorn uw_scan.api.server:app --host 0.0.0.0 --port 8400` | `127.0.0.1:8400:8400` | bind 0.0.0.0 inside container (drop the launchd `--host 127.0.0.1`); publish loopback-only for host health checks |
| `web` | node standalone | `3001:3001` | `NEXT_INTERNAL_API_BASE=http://api:8400`; `depends_on: api: service_healthy` |
| `ws-consumer` | `uv run python -m uw_scan.worker.massive_ws_consumer` | — | see xenon-feed env below |
| `worker-uw-0/1` | `uv run python -m uw_scan.worker.scheduler` | — | `UW_SCAN_WORKER_ROLE=uw`, `WORKER_INDEX=0/1` — explicit services, not replicas (per-instance INDEX) |
| `worker-massive-0/1` | same | — | `ROLE=massive` |
| `worker-ai-deepseek-0/1` | same | — | `ROLE=ai-deepseek` — HTTP + `DEEPSEEK_API_KEY`, container-safe |

All: `restart: unless-stopped`, `env_file: [/opt/argon/.env]`, `extra_hosts`, watchtower label.

Healthchecks: api = `curl -f http://localhost:8400/api/health`; web = `wget --spider -q http://127.0.0.1:3001/` (explicit IPv4 — alpine resolves `localhost` to `::1` first; xenon gotcha). Workers get a lightweight process-liveness check only (no HTTP surface).

**12 containers total.** Phase 1 is a lift-and-shift of the current topology; consolidating 2×uw/2×massive into fewer processes is a later optimization, not now.

## Env remaps (in `/opt/argon/.env`)

| Var | launchd value | container value |
|---|---|---|
| `UW_SCAN_DB_HOST` | `127.0.0.1` / `100.66.147.98` | `host.docker.internal` |
| `XENON_WS_URL` | `ws://127.0.0.1:8765` | `ws://host.docker.internal:8765` |
| `XENON_WS_PORT_FILE` | `/tmp/xenon-ib-realtime.json` | `""` (empty disables — the port file is host-local and invisible in-container; xenon publishes 8765 fixed from its own compose, so discovery is unnecessary) |
| `XENON_QUERY_API_URL` | `http://127.0.0.1:8321` | `http://host.docker.internal:8321` |
| `APEX_API_URL` | Tailscale IP | `http://host.docker.internal:8322` (apex publishes 8322) |
| `TRADE_INSIGHTS_AI_ENABLED` | true | **`false`** (Codex off) |
| `TRADE_INSIGHTS_AI_CLAUDE_ENABLED` | true | **`false`** (Claude off) |
| `TRADE_INSIGHTS_AI_DEEPSEEK_ENABLED` | true | true |

Massive WS already passes `proxy=None` explicitly — container-safe, preserve. Env rotation still requires container recreate (`docker-compose up -d --force-recreate <svc>`) — same freeze-at-fork semantics as today.

## Code changes required (one prep PR)

1. **`_enforce_db_isolation`** (`config.py:71-73`): add `host.docker.internal` as a legal host for `option_wizard` (prod container) and `option_wizard_local` (local compose testing). Without this the tripwire refuses startup — hard blocker.
2. **`web/next.config.mjs`**: `output: 'standalone'`.
3. **Dockerfiles** (`docker/app.Dockerfile`, `docker/web.Dockerfile`) + repo-committed `docker-compose.yml` (dev/build template; the mini's real file is `/opt/argon/compose.yml`, mirrored like apex).
4. **`release.yml`**: add `ghcr-push` job (matrix × 2 images, `ubuntu-24.04-arm`, after `publish`; prerelease tags excluded from `:latest`).
5. **Docs**: new runbook `docs/runbooks/docker-deploy.md`; mark launchd sections of `docs/runbooks/release.md` superseded (xenon precedent: keep old scripts, mark runbook superseded).
6. CHANGELOG entry — same PR.

## What stays on the host

- **Postgres 16/17 (Homebrew)** — untouched.
- **`com.argon.backup` / `com.argon.backup-r2`** launchd agents — they pg_dump the host DB with host `pg_dump`; containerizing them buys nothing. Keep. (Requires keeping a repo checkout on the mini for the backup scripts, or inlining the R2 script path — keep the checkout; it's also the rollback escape hatch.)
- **AI Codex/Claude workers** — retired in phase 1 (kill switches off, so no orphan queued rows: the API only enqueues rows for *enabled* providers). Interim fallback if Claude analyses are missed: their two launchd agents can keep running from the host checkout against the same DB — they're just Postgres pollers. Decision: **off by default**, hybrid only on request. Rewrite (API-based, e.g. Anthropic API runner like the DeepSeek shape) is a separate later project.
- **`com.argon.deploy-poller`** — retired, replaced by Watchtower.

## Deploy-semantics tradeoff (eyes open)

Today's `macmini-prod.sh` has health-gated rollback (currently broken — it accepts HTTP 200 with `ok=false`; see ops-hardening candidate). Watchtower has **no rollback**: a bad release runs until someone pins the previous tag (`sed` image tag in `/opt/argon/compose.yml` + `docker-compose up -d`). Mitigations:

- `release.yml` already gates publishing on the full verify suite (ruff, pytest incl. integration vs postgres:15, web build) — the class of "doesn't even boot" releases mostly can't publish.
- Compose `depends_on: service_healthy` + `restart: unless-stopped` keeps a crash-looping api from taking web down silently; `docker ps` shows unhealthy state.
- The ops-hardening candidate (webhook alert on `/api/health` `ok=false`) becomes the detection layer — recommend shipping it in the same window.

## Cutover plan (phased, reversible)

**Phase 0 — prep PR** (code changes above), CI green, merged. Local smoke: `docker-compose up` on the MacBook against `option_wizard_local` via `host.docker.internal`, run migrator, load `/`, `/api/health`.

**Phase 1 — mini side-by-side setup** (no cutover yet):
`colima stop && colima start --cpu 6 --memory 8` → GHCR `docker login` (same PAT approach as xenon) → create `/opt/argon/{compose.yml,.env}` → `docker-compose --profile migrate run --rm migrator` (idempotent, safe against live DB) → do **not** start app services yet.

**Phase 2 — cutover (the double-writer moment):**
1. `launchctl bootout gui/$UID` all `com.argon.*` app agents (api, web, massive-ws, 10 workers, deploy-poller) — **fully stopped before compose starts**; running both stacks double-writes and double-burns the UW budget (known gotcha from the xenon-WS migration).
2. `docker-compose up -d` at `/opt/argon`.
3. Verify: `/api/health` `ok=true` + `ws_consumer.active_source=xenon_ws` (proves host.docker.internal:8765 works) + one full scan cycle lands + freshness monitor green next morning + spot updates visible on `:3001`.

**Phase 3 — retire:** after ~3 clean days, remove app plists from `~/Library/LaunchAgents` (keep backup plists). Update `config/services.list` docs.

**Rollback at any point:** `docker-compose down` → `launchctl bootstrap` the plists back (they stay on disk through phase 2) → old stack resumes from the same DB. No data migration in either direction — DB never moved.

## Verification checklist

- [ ] tripwire: container boots against `host.docker.internal`/`option_wizard`; still refuses illegal pairs (unit test)
- [ ] xenon WS primary connects from container; failover to massive still works (kill xenon relay, watch `active_source` flip)
- [ ] xenon query API reachable (surface IV canary writes `iv_source_validation` rows with `source='ib'`)
- [ ] UW scan cycle completes; budget governor counters sane (no double burn)
- [ ] DeepSeek analysis end-to-end (enqueue via web → worker claims → result renders)
- [ ] massive WS connects with no proxy env leakage
- [ ] Watchtower recreates on a test prerelease→release publish
- [ ] nightly backup still runs (host launchd, untouched)

## Open items

- Colima VM sizing is shared with xenon/apex containers — watch memory after cutover; workers are idle-poll APScheduler processes (~100-150 MB RSS each expected).
- Postgres version drift: argon backup plist pins `postgresql@16`, xenon/apex docs say host runs `@17` — confirm which instance actually serves `option_wizard` on the mini before phase 1 (affects only the backup plist's pg_dump path, not the containers).
- AI rewrite (Codex/Claude → API-based runners) — separate spec, later.
