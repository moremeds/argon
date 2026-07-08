# Argon Docker migration — design

**Date:** 2026-07-06 · **Status:** PREP-PR IN FLIGHT 2026-07-08 (branch `feat/docker-migration-prep`; all load-bearing claims re-verified against source + the mini's live Watchtower — engine-wide `WATCHTOWER_LABEL_ENABLE=true`, 60s poll, GHCR creds present. Two cutover gaps folded: Colima resize = cross-project VM bounce; Watchtower alerts route to xenon's ntfy topic. `uv run` dropped from container commands — `.venv` on PATH.)
**Goal:** move the argon prod stack off launchd into Docker on the Mac mini, matching the xenon/apex house pattern (Colima, bridge network + `host.docker.internal`, host-native Postgres, GHCR images from `release.yml`, Watchtower auto-deploy). AI analysis (Codex/Claude CLI) is knowingly sacrificed in phase 1 and rewritten later; DeepSeek survives.

## House pattern adopted (verified from xenon/apex)

- **Runtime:** Colima VM on the mini (brew service). xenon default profile is 2 CPU / 2 GiB — argon adds ~10 services (9 long-running + a one-shot migrator), so resize to `colima start --cpu 6 --memory 8` (xenon docs already flag OOM risk at 2 GiB with 4 containers).
- **Networking:** bridge, published ports, `extra_hosts: ["host.docker.internal:host-gateway"]` on every service. Never `127.0.0.1` for host resources ("127.0.0.1 is the container itself" — xenon runbook).
- **Postgres:** stays host-native Homebrew. Containers reach it at `host.docker.internal:5432`, DB `option_wizard`, role `argon_app`. No data moves.
- **Images:** built/pushed by `.github/workflows/release.yml` on `ubuntu-24.04-arm` (native arm64, no QEMU — apex pattern) to GHCR, tags `:X.Y.Z` + `:latest` (prereleases excluded from `:latest`).
- **Deploy:** apex-style — compose file mirrored at `/opt/argon/compose.yml`, app services carry `com.centurylinklabs.watchtower.enable: "true"`. The single engine-wide Watchtower already in `/opt/xenon/compose.yml` polls GHCR every 60s and recreates on new `:latest`. **Verified on the mini (2026-07-08):** `WATCHTOWER_LABEL_ENABLE=true`, no `WATCHTOWER_SCOPE`, docker.sock mounted, GHCR `REPO_USER/PASS` present → it watches *any* labelled container engine-wide, so argon's labelled services are picked up with no second Watchtower. **Do not add a second Watchtower.** This preserves argon's current auto-deploy UX (deploy-poller retires). **Caveat:** that Watchtower's `WATCHTOWER_NOTIFICATION_URL` posts to `ntfy://ntfy.sh/xenon-deploy-…` titled "Xenon auto-deploy" — so argon container updates will alert on **xenon's** ntfy topic, branded as xenon. Cosmetic (one shared deploy channel for the mini); accept it, or split topics later — not worth a second Watchtower.
- **Mini quirks:** hyphenated `docker-compose` (brew v5.1.3); SSH needs `PATH=/opt/homebrew/bin:$PATH`; Colima starts at user login only (auto-login tradeoff already accepted for xenon).

## Images (2, not 4 — deliberate simplification vs xenon)

xenon ships 4 near-identical Dockerfiles. Argon's api/workers/ws-consumer/migrator all run the same Python package, so:

1. **`ghcr.io/moremeds/argon-app`** — multi-stage `python:3.13-slim`; uv static binary (`COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/`), `uv sync --frozen --no-dev --extra postgres` in builder, runtime copies `.venv` + `src` + `scripts/` + `db` migrations, installs `libpq5 ca-certificates curl tini`; tini is PID 1. No default CMD dependence — each compose service sets `command:`.
2. **`ghcr.io/moremeds/argon-web`** — `node:22-alpine` multi-stage, Next.js **standalone output** (requires `output: 'standalone'` in `web/next.config.mjs`), `CMD ["node", "server.js"]`.

## Compose topology (`/opt/argon/compose.yml`)

| Service | command | ports | notes |
|---|---|---|---|
| `migrator` | `python -m uw_scan.storage.migrate_runner` (in-process psycopg, no psql needed) | — | `profiles: ["migrate"]`, `restart: "no"` — never auto-runs on `up -d` (xenon pattern) |
| `api` | `uvicorn uw_scan.api.server:app --host 0.0.0.0 --port 8400` | `127.0.0.1:8400:8400` | bind 0.0.0.0 inside container (drop the launchd `--host 127.0.0.1`); publish loopback-only for host health checks |
| `web` | node standalone | `3001:3001` | `NEXT_INTERNAL_API_BASE=http://api:8400` (runtime rewrite proxy for client `/api/*`); `depends_on: api: service_healthy`. **Also needs the SSR base — see code change #7 + env table** |
| `ws-consumer` | `python -m uw_scan.worker.massive_ws_consumer` | — | see xenon-feed env below |
| `worker-uw-0/1` | `python -m uw_scan.worker.scheduler` | — | `UW_SCAN_WORKER_ROLE=uw`, `WORKER_INDEX=0/1` — explicit services, not replicas (per-instance INDEX) |
| `worker-massive-0/1` | same | — | `ROLE=massive` |
| `worker-ai-deepseek-0/1` | same | — | `ROLE=ai-deepseek` — HTTP + `DEEPSEEK_API_KEY`, container-safe |

> **No `uv run` prefix in-container.** The app image installs the project into `.venv` (`uv sync --frozen`) and puts `/app/.venv/bin` on `PATH` (xenon-migrator pattern), so `uvicorn`/`python`/the `uw_scan` package resolve directly. `uv` is a build-stage-only tool — it is **not** shipped in the runtime image, and the migrator runs the module directly rather than the `scripts/migrate.sh` wrapper (which is a host convenience that shells out to `uv run`).

All: `restart: unless-stopped`, `env_file: [/opt/argon/.env]`, `extra_hosts`, watchtower label.

Healthchecks: api = `curl -f http://localhost:8400/api/health`; web = `wget --spider -q http://127.0.0.1:3001/` (explicit IPv4 — alpine resolves `localhost` to `::1` first; xenon gotcha). Workers get a lightweight process-liveness check only (no HTTP surface).

**10 services** (api + web + ws-consumer + 2×uw + 2×massive + 2×ai-deepseek = 9 long-running, plus a profile-gated one-shot migrator). Phase 1 is a lift-and-shift of the current topology; consolidating 2×uw/2×massive into fewer processes is a later optimization, not now.

## Env remaps (in `/opt/argon/.env`)

| Var | launchd value | container value |
|---|---|---|
| `UW_SCAN_DB_HOST` | `127.0.0.1` / `100.66.147.98` | `host.docker.internal` |
| `XENON_WS_URL` | `ws://127.0.0.1:8765` | `ws://host.docker.internal:8765` |
| `XENON_WS_PORT_FILE` | `/tmp/xenon-ib-realtime.json` | `""` (empty disables — the port file is host-local and invisible in-container; xenon publishes 8765 fixed from its own compose, so discovery is unnecessary) |
| `XENON_QUERY_API_URL` | `http://127.0.0.1:8321` | `http://host.docker.internal:8321` |
| `APEX_API_URL` | Tailscale IP | `http://host.docker.internal:8322` (apex publishes 8322) |
| `NEXT_INTERNAL_API_BASE` | (unset → `localhost:8400`) | `http://api:8400` — **runtime** (next.config.mjs rewrite); works via `/opt/argon/.env` |
| `NEXT_PUBLIC_API_BASE_URL` / `NEXT_PUBLIC_API_BASE` | `""` (build) → SSR falls back to `127.0.0.1:8400` | **DO NOT set at runtime** — `NEXT_PUBLIC_*` is build-inlined; a runtime value in `.env` is a no-op. Fixed in code change #7 (SSR reads a non-public var instead) |
| `TRADE_INSIGHTS_AI_ENABLED` | true | **`false`** (Codex off) |
| `TRADE_INSIGHTS_AI_CLAUDE_ENABLED` | true | **`false`** (Claude off) |
| `TRADE_INSIGHTS_AI_DEEPSEEK_ENABLED` | true | true |

Massive WS already passes `proxy=None` explicitly — container-safe, preserve. Env rotation still requires container recreate (`docker-compose up -d --force-recreate <svc>`) — same freeze-at-fork semantics as today.

## Code changes required (one prep PR)

1. **`_enforce_db_isolation`** (`config.py:70-74`, `_HOST_DB_RULES`): add
   `"host.docker.internal": frozenset({"option_wizard", "option_wizard_local", "option_wizard_test"})`.
   Without this the tripwire refuses container startup. **And keep the tripwire
   meaningful:** do NOT carry `UW_SCAN_ALLOW_DB_MISMATCH=1` into `/opt/argon/.env`.
   (The mini's *launchd* `.env` sets that override for its `127.0.0.1`+`option_wizard`
   route — PR #246 — but the override bypasses ALL isolation checks. If the container
   `.env` inherited it, this code change would be redundant and the container would run
   with isolation silently disabled. The clean container path is: legal `host.docker.internal`
   pair + no override.)
2. **`web/next.config.mjs`**: `output: 'standalone'`.
3. **Dockerfiles** (`docker/app.Dockerfile`, `docker/web.Dockerfile`) + repo-committed `docker-compose.yml` (dev/build template; the mini's real file is `/opt/argon/compose.yml`, mirrored like apex).
4. **`release.yml`**: add `ghcr-push` job (matrix × 2 images, `ubuntu-24.04-arm` — free on this PUBLIC repo, no self-hosted runner needed; `needs: verify`, runs alongside/after `publish`; prerelease tags excluded from `:latest`). The job needs `permissions: packages: write` and a `docker/login-action` step against `ghcr.io` with `GITHUB_TOKEN` — neither exists in the current workflow.
5. **Docs**: new runbook `docs/runbooks/docker-deploy.md`; mark launchd sections of `docs/runbooks/release.md` superseded (xenon precedent: keep old scripts, mark runbook superseded).
6. CHANGELOG entry — same PR.
7. **Web SSR API base** — the server-render fetch path currently reads
   `process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8400"`
   (`web/lib/api.ts:22`, `web/lib/regime/api.ts:9`, `web/app/admin/page.tsx:9`) and
   `NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8400"` (`web/app/gold/page.tsx:7`,
   `web/app/gold/replay/[date]/page.tsx:7`). `NEXT_PUBLIC_*` is inlined at **build**
   time, so `/opt/argon/.env` cannot override it — inside the `web` container the SSR
   base falls back to `127.0.0.1:8400` = the container itself → every server-rendered
   page fails its data fetch (including `/`). Change the server-side branch of these
   files to read a **non-public runtime var** — reuse `NEXT_INTERNAL_API_BASE`
   (`?? "http://127.0.0.1:8400"` for host/launchd compat) — so one runtime env drives
   both the client rewrite and the SSR base. Do this in code, not via a build ARG, to
   avoid baking the compose service name into the image. Hard cutover-blocker if missed.

## What stays on the host

- **Postgres 16/17 (Homebrew)** — untouched.
- **`com.argon.backup` / `com.argon.backup-r2`** launchd agents — they pg_dump the host DB with host `pg_dump`; containerizing them buys nothing. Keep. (Requires keeping a repo checkout on the mini for the backup scripts, or inlining the R2 script path — keep the checkout; it's also the rollback escape hatch.)
- **AI Codex/Claude workers** — retired in phase 1 (kill switches off, so no orphan queued rows: the API only enqueues rows for *enabled* providers). Interim fallback if Claude analyses are missed: their two launchd agents can keep running from the host checkout against the same DB — they're just Postgres pollers. Decision: **off by default**, hybrid only on request. Rewrite (API-based, e.g. Anthropic API runner like the DeepSeek shape) is a separate later project — tracked in **issue #248**.
- **`com.argon.deploy-poller`** — retired, replaced by Watchtower.

## Deploy-semantics tradeoff (eyes open)

Today's `macmini-prod.sh` gates on **serving liveness** (`.db == "up"` + deployed
`.version`), NOT `.ok` — PR #247 corrected the earlier `.ok`-based gate that deadlocked
under budget throttling. Watchtower has **no rollback**: a bad release runs until someone
pins the previous tag (`sed` image tag in `/opt/argon/compose.yml` + `docker-compose up -d`).
Mitigations:

- `release.yml` already gates publishing on the full verify suite (ruff, pytest incl. integration vs postgres:15, web build) — the class of "doesn't even boot" releases mostly can't publish.
- Compose `depends_on: service_healthy` + `restart: unless-stopped` keeps a crash-looping api from taking web down silently; `docker ps` shows unhealthy state. **The container HEALTHCHECK (`curl -f …/api/health`, HTTP-200-only — see topology table) deliberately does NOT parse `.ok`, so it stays green during budget throttle and won't false-fail `depends_on` — the same #247 lesson, applied to the container layer.**
- The C12 ops-hardening alert (webhook on job-failure streak / budget wall — already shipped, v0.8.0) is the detection layer for runtime-broken-but-published releases, since Watchtower can't roll back.

## Cutover plan (phased, reversible)

**Phase 0 — prep PR** (code changes above), CI green, merged. Local smoke: `docker-compose up` on the MacBook against `option_wizard_local` via `host.docker.internal`, run migrator, load `/`, `/api/health`.

**Phase 1 — mini side-by-side setup** (no cutover yet):
`colima stop && colima start --cpu 6 --memory 8` → GHCR `docker login` (same PAT approach as xenon) → create `/opt/argon/{compose.yml,.env}` → `docker-compose --profile migrate run --rm migrator` (idempotent, safe against live DB) → do **not** start app services yet.

> **⚠ The Colima resize is NOT argon-local — it bounces the whole mini.** There is one shared Colima VM (verified 2026-07-08: 4 CPU / ~5.77 GiB) hosting **xenon (live IB feed), apex, and the trading-observability stack** (alloy/prometheus/grafana/loki/cadvisor). `colima stop` kills all of them simultaneously; `colima start` must bring all three back. So: **schedule this in a market-closed window** (xenon's IB feed and any live positions go dark during the bounce), and after `colima start` verify **all three stacks return healthy** (`docker ps` all `Up`/`healthy`, xenon `/api/health`, apex `:8322/health`, Grafana reachable) *before* touching argon. Current VM use is ~2.2 GiB; argon's ~9 long-running containers add ~2 GiB, so the resize to 8 GiB is required headroom, not optional — do not skip it and try to fit argon into the current 5.77 GiB.

**Phase 2 — cutover (the double-writer moment):**
1. `launchctl bootout gui/$UID` all `com.argon.*` app agents (api, web, massive-ws, 10 workers, deploy-poller) — **fully stopped before compose starts**; running both stacks double-writes and double-burns the UW budget (known gotcha from the xenon-WS migration).
2. `docker-compose up -d` at `/opt/argon`.
3. Verify **serving liveness, NOT `.ok`** (post-#247: `.ok` folds in budget-throttled
   skipped full scans and is routinely `false` during RTH — gating cutover on it would
   read a healthy stack as a failed deploy): `/api/health` `.db == "up"` + `.version`
   matches the deployed tag + `ws_consumer.active_source=xenon_ws` (proves
   host.docker.internal:8765 works) + one full scan cycle lands + **server-rendered pages
   render data — load `/`, `/gold`, and a `/stock/<ticker>` page, not just `/api/health`
   (catches the SSR-base regression, code change #7)** + freshness monitor green next
   morning + spot updates visible on `:3001`.

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
- [ ] **web SSR renders data from inside the container** — `/`, `/gold`, `/stock/<ticker>`, `/regime` all fetch (not just `/` + `/api/health`); confirms code change #7 landed and the SSR base is `api:8400`, not `127.0.0.1:8400`
- [ ] tripwire is still ACTIVE in-container (no `UW_SCAN_ALLOW_DB_MISMATCH=1` in `/opt/argon/.env`); illegal `(host, db)` still refuses

## Open items

- Colima VM sizing is shared with xenon/apex containers — watch memory after cutover; workers are idle-poll APScheduler processes (~100-150 MB RSS each expected).
- ~~Postgres version drift: argon backup plist pins `postgresql@16`…~~ **RESOLVED by PR #246** — backup plist now uses `postgresql@17`, matching the host cluster. No longer an open item.
- AI rewrite (Codex/Claude → API-based runners) — separate spec, later.
