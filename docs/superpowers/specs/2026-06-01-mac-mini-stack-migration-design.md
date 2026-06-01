# Mac mini stack migration — design

**Status:** Draft, awaiting user approval before plan
**Author:** brainstorm session 2026-06-01
**Target host:** Mac mini, Tailscale `100.66.147.98`, SSH user `moremeds`
**Sibling project on same host:** xenon (already deployed; this design reuses xenon's host infrastructure)

---

## AMENDMENT 2026-06-01 (post-implementation)

The implementation differs from this spec in four places, made during Phase 1 execution. The amendments are reflected in the code under `scripts/deploy/`, `config/templates/`, `src/uw_scan/config.py`, `.env.example`, `tests/`, `CLAUDE.md`, `AGENTS.md`, `README.md`, and `docs/ops/macmini-runbook.md`. This spec body below is left in its original form for design-decision audit purposes.

1. **DB names kept as `option_wizard` / `option_wizard_test`** (not renamed to `argon_dev` / `argon_test`). Rationale: the original spec's `argon_dev` collided with the password literal `argon_dev` — same string for two semantically distinct values is a code-smell. Retaining `option_wizard` also avoids a no-op rename across ~30 references with zero functional benefit.
2. **Password auto-generated via `openssl rand -base64 24`** (not a static `argon_dev` default). `macmini-bootstrap.sh` generates on first run, reads existing value from `.env` on re-runs (idempotent), and `ALTER ROLE` syncs to the role. Stored in `${ARGON_HOME}/.env` (chmod 600) and `~/.pgpass` (chmod 600). Printed once at bootstrap end for copy into MacBook `.env.local`.
3. **`~/.pgpass` replaces inline `PGPASSWORD=...` everywhere** — backup plist, data-promote.sh, restore commands in the runbook. The pg* CLI tools auto-read it; no plaintext passwords in plist `EnvironmentVariables` dicts, no inline env vars in ssh-side commands.
4. **Claude/Codex CLI auth probes are advisory, not gating.** Original design had bootstrap `die` if either probe failed. New behavior: probe-and-warn; the affected `ai-claude` / `ai-codex` worker plists are rendered but not loaded (no crash-loop), and the summary prints the exact `launchctl load …` commands to run after fixing auth. Core stack (API, web, uw/massive workers, ai-deepseek) loads regardless. Rationale: the AI worker auth state shouldn't block deployment of services that don't depend on it.

Schema stays `uw_scan`. Role stays `argon_app` (NOSUPERUSER NOCREATEDB NOCREATEROLE). Mac mini topology and all other design decisions are unchanged.

---

## 1. Motivation and scope

Today the entire `unusual-whales` stack — Next.js web, FastAPI, six fetcher workers, six AI workers, one massive WS consumer, and the `option_wizard` Postgres DB — runs as host processes on the user's MacBook Pro via `scripts/dev.sh`. The MacBook is the de-facto production host. Closing the laptop, sleep cycles, and laptop restarts all stop data collection and serving.

The Mac mini at `100.66.147.98` already hosts xenon under launchd and a shared Homebrew `postgresql@16` cluster. This design moves the entire `unusual-whales` stack onto that same Mac mini, mirroring xenon's deployment shape so the user has one operational model to maintain for both projects.

**In scope:**
- Move all 13 long-running processes to the Mac mini under launchd
- Move the `option_wizard` Postgres DB to the Mac mini's existing `postgresql@16` cluster, renamed to `argon_dev` (with new `argon_test`)
- Introduce a non-superuser app role `argon_app` (mirrors xenon's `xenon_app`)
- Update the MacBook's `.env` to point `UW_SCAN_DB_*` at the mini over Tailscale
- Provide three deploy scripts (`macmini-bootstrap.sh`, `macmini-prod.sh`, `macmini-data-promote.sh`) mirroring xenon's
- Provide four launchd plist templates (`api`, `web`, `worker`, `massive-ws`)

**Out of scope:**
- Docker containerization (mini runs everything via launchd — same as xenon, no Docker)
- Replicating to a third host for HA — single-host design, accepted blast radius
- Public network exposure — Tailscale-only access, no Cloudflare Tunnel or reverse proxy
- Changing the MacBook's local-dev story beyond the DB host swap (`scripts/dev.sh` keeps working, just hitting the mini DB)
- Migrating archived docs that reference `option_wizard` (historical record stays accurate)

---

## 2. Target topology

```
┌─────────────────────────────┐         ┌──────────────────────────────────────────┐
│  MacBook Pro                 │         │  Mac mini @ 100.66.147.98 (moremeds)     │
│  ─────────────               │         │  ───────────────────────────              │
│  • Editor                    │         │  ┌──────────────────────────────────┐   │
│  • git push origin <branch>  │ Tailnet│  │ Host (macOS arm64, no Docker)    │   │
│  • scripts/dev.sh             │ ◄────► │  │                                   │   │
│    UW_SCAN_DB_HOST=          │         │  │  postgresql@16 (Homebrew, already│   │
│    100.66.147.98             │         │  │  installed for xenon)             │   │
│    UW_SCAN_DB_NAME=argon_dev │         │  │   • DB: xenon_db (xenon)          │   │
│    UW_SCAN_DB_USER=argon_app │         │  │   • DB: core_dev/_test (xenon)    │   │
│    UW_SCAN_DB_PASSWORD=      │         │  │   • DB: argon_dev   ← new         │   │
│    argon_dev                 │         │  │   • DB: argon_test  ← new         │   │
│  • psql to mini DB ad-hoc    │         │  │                                   │   │
│                              │         │  │  Roles                            │   │
│  • Does NOT run web/API/wkrs │         │  │   • moremeds  (superuser, OS user)│   │
│    (those live on mini)      │         │  │   • xenon_app (xenon's app)       │   │
└─────────────────────────────┘         │  │   • argon_app ← new (NOSUPERUSER, │   │
                                         │  │     owner of argon_dev/argon_test)│   │
                                         │  └──────────────────────────────────┘   │
                                         │  ┌──────────────────────────────────┐   │
                                         │  │ launchd jobs (13 for argon)      │   │
                                         │  │  com.argon.api          :8400    │   │
                                         │  │  com.argon.web          :3001    │   │
                                         │  │  com.argon.massive-ws            │   │
                                         │  │  com.argon.worker.uw-{0,1}       │   │
                                         │  │  com.argon.worker.massive-{0,1}  │   │
                                         │  │  com.argon.worker.ai-codex-{0,1} │   │
                                         │  │  com.argon.worker.ai-claude-{0,1}│   │
                                         │  │  com.argon.worker.ai-deepseek-   │   │
                                         │  │    {0,1}                          │   │
                                         │  │                                   │   │
                                         │  │ Codex CLI + Claude CLI already   │   │
                                         │  │ signed in for `moremeds` (xenon  │   │
                                         │  │ uses them too)                    │   │
                                         │  └──────────────────────────────────┘   │
                                         └──────────────────────────────────────────┘
```

**Why no Docker on the mini:** xenon proved out the launchd-only pattern. Containerizing the AI workers (`com.argon.worker.ai-codex-*`, `com.argon.worker.ai-claude-*`) would break their keychain OAuth — they invoke `codex exec` and `claude --print` as subprocesses, and per project policy the env allow-list strips `ANTHROPIC_API_KEY` so subscription auth wins. Running everything as launchd jobs gives one operational shape (logs, restart, env) for all 13 processes.

**Why a separate role:** `moremeds` is superuser and the OS account. Connecting the app as a non-superuser `argon_app` constrains the blast radius of a compromised app process — it can DDL within its own DBs (needed for `scripts/migrate.sh`) but cannot create extensions, drop other DBs, or alter other roles.

**Why shared cluster, separate DBs:** one Postgres process to maintain (already running for xenon). DB-level isolation between projects: `argon_app` cannot connect to `core_dev` / `xenon_db`; `xenon_app` cannot connect to `argon_dev` / `argon_test`. Both projects share `moremeds` as the admin for cross-project maintenance only.

---

## 3. DB rename and role design

### 3.1 New roles and databases (on the mini)

Created once by `scripts/deploy/macmini-bootstrap.sh`, idempotently:

```sql
-- App role, non-superuser, mirrors xenon's xenon_app
CREATE ROLE argon_app LOGIN PASSWORD 'argon_dev'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;

-- Workspace DB (renamed from option_wizard on the source side)
CREATE DATABASE argon_dev OWNER argon_app;

-- Test DB (new — does not exist today on MacBook)
CREATE DATABASE argon_test OWNER argon_app;

-- The schema uw_scan stays the same name within each DB
-- (created by the first run of scripts/migrate.sh, idempotent)
```

### 3.2 Connection strings

The codebase reads individual `UW_SCAN_DB_*` env vars, not `DATABASE_URL`. Keep that shape, change the values:

```
# MacBook .env (for dev sessions of scripts/dev.sh or ad-hoc psql)
UW_SCAN_DB_HOST=100.66.147.98
UW_SCAN_DB_PORT=5432
UW_SCAN_DB_NAME=argon_dev
UW_SCAN_DB_SCHEMA=uw_scan
UW_SCAN_DB_USER=argon_app
UW_SCAN_DB_PASSWORD=argon_dev

# Mac mini .env (workers/API/web on the mini reach Postgres via localhost)
UW_SCAN_DB_HOST=127.0.0.1
UW_SCAN_DB_PORT=5432
UW_SCAN_DB_NAME=argon_dev
UW_SCAN_DB_SCHEMA=uw_scan
UW_SCAN_DB_USER=argon_app
UW_SCAN_DB_PASSWORD=argon_dev
```

### 3.3 pg_hba.conf

xenon's bootstrap already configured the mini's `pg_hba.conf` to accept Tailnet CGNAT (`100.64.0.0/10`) with `scram-sha-256`. No changes needed — the same rule covers `argon_app` connecting from MacBook.

### 3.4 Codebase rename scope (live, not archive)

| Location | Files | Notes |
|---|---|---|
| `src/` | 1 | Likely a default fallback string somewhere in storage layer |
| `tests/` | 7 | Fixture DB names — must change to `argon_test` |
| `scripts/` | 1 | Likely `migrate.sh` or one of the diagnostic scripts |
| Root active docs | 5 | `.env`, `.env.example`, `CLAUDE.md`, `AGENTS.md`, `README.md` |
| Active specs/plans (not `archive/`) | 3 | Self-explanatory mentions |
| **Total live** | **~17 files** | |
| `docs/.../archive/` | 17 | **Leave alone** — historical record; archive must remain accurate to its date |

Implementation note: the plan will do this rename in a single commit (`chore/rename-option-wizard-to-argon-dev`) preceding any Mac mini work, so the rename diff is reviewable on its own. Tests in CI must pass against the new name before we touch deployment.

---

## 4. Deploy scripts (`scripts/deploy/`)

Three new scripts, all 1:1 ports of xenon's equivalents.

### 4.1 `macmini-bootstrap.sh` — first-time setup on the mini

Idempotent, probe-and-skip per step. Runs as `moremeds` on the mini. Differences from xenon's bootstrap (because xenon already set up the host):

| Step | What changes vs xenon's bootstrap |
|---|---|
| Xcode CLT | Skip — already installed by xenon's run |
| Homebrew | Skip — already installed |
| `postgresql@16` install + start | Skip — already running for xenon |
| Node, uv, gh | Skip — already installed |
| `gh` auth, SSH key | Skip — already done for xenon |
| **Create role `argon_app`** | NEW — not part of xenon's bootstrap |
| **Create DBs `argon_dev` + `argon_test`** | NEW |
| Clone repo to `~/projects/unusual-whales` | New, but identical pattern (`git@github.com:...`) |
| **Verify Claude CLI + Codex CLI signed in for `moremeds`** | NEW — xenon doesn't use them, must check explicitly |
| Scaffold `.env` from `.env.example` (pre-fill `UW_SCAN_DB_*`) | New, identical pattern |
| `uv sync --frozen` | New, identical pattern |
| `cd web && npm install --legacy-peer-deps && npm run build` | New, identical pattern |
| `bash scripts/migrate.sh` | New — `argon_dev` schema bootstrap (idempotent) |
| Render + load 13 launchd plists | New, scaled-up version of xenon's 3-plist loop |
| Health checks | New — `curl :8400/health`, `curl -I :3001`, count `uw_scan.scan_runs` rows |

**Refuses to run** unless `pgrep -q postgres` and `psql -d postgres -c "SELECT 1"` succeed (xenon's Postgres must be up).

**Refuses to run** unless `claude auth status` and `codex auth status` (or equivalent) confirm subscription auth — without these, the AI workers will load and immediately fail.

### 4.2 `macmini-prod.sh <tag>` — recurring deploys with rollback

Identical control flow to xenon's. Refuses to run anywhere except the mini (probes `~/Library/LaunchAgents/com.argon.api.plist`), checks out a tag, rebuilds, runs `scripts/migrate.sh`, kickstarts all 13 services, health-checks, rolls back on failure.

The kickstart loop reads from `config/services.list` (one source of truth for the 13 service labels) instead of hardcoding three labels like xenon does:

```bash
while IFS= read -r label; do
  [[ -z "$label" || "$label" == \#* ]] && continue
  launchctl kickstart -k "gui/$UID/$label"
done < config/services.list
```

`config/services.list` (committed file):
```
com.argon.api
com.argon.web
com.argon.massive-ws
com.argon.worker.uw-0
com.argon.worker.uw-1
com.argon.worker.massive-0
com.argon.worker.massive-1
com.argon.worker.ai-codex-0
com.argon.worker.ai-codex-1
com.argon.worker.ai-claude-0
com.argon.worker.ai-claude-1
com.argon.worker.ai-deepseek-0
com.argon.worker.ai-deepseek-1
```

### 4.3 `macmini-data-promote.sh <ssh-host> [--confirm]` — laptop → mini DB mirror

Run from the **MacBook**, destructive on the target. Xenon's script is the template; differences:

| Step | What changes |
|---|---|
| Refuse if local writers listening | Probe ports `8400` and `3001` (not 8321/3000) AND `pgrep -f "uw_scan.worker.scheduler\|massive_ws_consumer"` |
| Local pg_dump | `pg_dump -h localhost -Fc --no-owner --no-acl -f data/backups/option_wizard-<ts>.dump option_wizard` |
| Ship + restore | `ssh moremeds@<host> "pg_restore --clean --if-exists --no-owner --no-acl -d argon_dev" < dump` (note: source `option_wizard`, target `argon_dev` — `--no-owner` strips ownership so target's `argon_app` ownership is preserved) |
| Verify | `ssh moremeds@<host> "psql argon_dev -c \"SELECT relname, n_live_tup FROM pg_stat_user_tables WHERE schemaname='uw_scan' ORDER BY n_live_tup DESC LIMIT 20\""` |
| Kickstart | `ssh moremeds@<host> 'cd ~/projects/unusual-whales && while read s; do launchctl kickstart -k gui/$UID/$s; done < config/services.list'` |

**Acceptable downtime: ~15 min** for the initial cutover (5 min dump + 5 min Tailscale ship + ~5 min restore with index rebuild on an 8.2 GB DB).

---

## 5. launchd plist templates (`config/templates/`)

Four templates, all in the xenon-style `sed`-substitution shape. Placeholders: `__PROJECT_DIR__`, `__USER__`, `__BREW_PREFIX__`, `__UV_BIN__`, `__NODE_BIN__`, `__NPM_BIN__`, plus per-worker `__ROLE__`, `__INDEX__`, `__COUNT__`.

### 5.1 `com.argon.api.plist.template`

```xml
<key>ProgramArguments</key>
<array>
  <string>__UV_BIN__</string><string>run</string><string>uvicorn</string>
  <string>uw_scan.api.server:app</string>
  <string>--host</string><string>127.0.0.1</string>
  <string>--port</string><string>8400</string>
</array>
```

No `--reload` (prod). `KeepAlive.Crashed=true, SuccessfulExit=false`. Logs to `__PROJECT_DIR__/logs/api.{out,err}.log`.

### 5.2 `com.argon.web.plist.template`

```xml
<key>ProgramArguments</key>
<array>
  <string>__NODE_BIN__</string>
  <string>web/.next/standalone/server.js</string>
</array>
<key>EnvironmentVariables</key>
<dict>
  <key>PORT</key><string>3001</string>
  <key>HOSTNAME</key><string>127.0.0.1</string>
  ...
</dict>
```

Standalone Next.js output; `npm run build` produces `web/.next/standalone/server.js`. Required to also copy `web/.next/static` and `web/public` to the standalone dir post-build (Next.js standalone quirk) — handled in `macmini-prod.sh`.

### 5.3 `com.argon.worker.plist.template`

Parameterized template — rendered once per `(role, index)` pair: 10 instances total (uw×2, massive×2, ai-codex×2, ai-claude×2, ai-deepseek×2).

```xml
<key>Label</key>
<string>com.argon.worker.__ROLE__-__INDEX__</string>

<key>ProgramArguments</key>
<array>
  <string>__UV_BIN__</string><string>run</string><string>python</string>
  <string>-m</string><string>uw_scan.worker.scheduler</string>
</array>

<key>EnvironmentVariables</key>
<dict>
  <key>UW_SCAN_WORKER_ROLE</key><string>__ROLE__</string>
  <key>UW_SCAN_WORKER_INDEX</key><string>__INDEX__</string>
  <key>UW_SCAN_WORKER_COUNT</key><string>__COUNT__</string>
  <key>UW_SCAN_UW_WORKER_COUNT</key><string>2</string>
  <key>UW_SCAN_MASSIVE_WORKER_COUNT</key><string>2</string>
  <key>UW_SCAN_AI_WORKER_COUNT</key><string>2</string>
  <key>TRADE_INSIGHTS_AI_CODEX_WORKER_COUNT</key><string>2</string>
  <key>TRADE_INSIGHTS_AI_CLAUDE_WORKER_COUNT</key><string>2</string>
  <key>TRADE_INSIGHTS_AI_DEEPSEEK_WORKER_COUNT</key><string>2</string>
  <key>MASSIVE_WS_ENABLED</key><string>true</string>
  <key>PATH</key>
  <string>__BREW_PREFIX__/bin:/usr/local/bin:/usr/bin:/bin</string>
  <key>HOME</key><string>/Users/__USER__</string>
  <key>USER</key><string>__USER__</string>
</dict>
```

`USER` is required by the existing Claude/Codex runner code (`trade_insights_ai_runners.py`) — without it, the OAuth keychain lookup misses and the runner fails. xenon's plists already do this.

### 5.4 `com.argon.massive-ws.plist.template`

Similar shape, but `ProgramArguments` runs `python -m uw_scan.worker.massive_ws_consumer`. Single instance, no `__INDEX__`/`__COUNT__`.

---

## 6. Dev workflow (MacBook ↔ Mac mini)

### 6.1 Day-to-day code change

```
[MacBook] edit → commit → git push origin feature/foo
[MacBook] scripts/deploy/macmini-deploy-branch.sh feature/foo
            └─ ssh moremeds@100.66.147.98 \
                  "cd ~/projects/unusual-whales \
                   && git fetch origin && git checkout feature/foo \
                   && git pull --ff-only \
                   && uv sync --frozen \
                   && cd web && npm install --legacy-peer-deps && npm run build && cd .. \
                   && bash scripts/migrate.sh \
                   && while read s; do launchctl kickstart -k gui/\$UID/\$s; \
                      done < config/services.list"
```

Wrapped into a single MacBook command. Round trip ~60-90s for typical edits (mostly the `npm run build`). For Python-only changes that don't need a web rebuild, a faster variant skips the npm steps.

### 6.2 Ad-hoc DB inspection

```
psql -h 100.66.147.98 -U argon_app -d argon_dev
# password: argon_dev (from .env, mode 0600)
```

### 6.3 Local-only dev (rare, but well-defined)

After migration, the MacBook's `.env` points `UW_SCAN_DB_HOST=100.66.147.98`. **Running `scripts/dev.sh` as-is would start MacBook workers writing to the mini DB and competing with mini workers on the same `FOR UPDATE SKIP LOCKED` queue** (the race condition flagged in brainstorming). To prevent this, the design adds two mechanisms:

1. **`scripts/dev.sh` guard** — at the top, the script refuses to run if `UW_SCAN_DB_HOST != 127.0.0.1` unless `UW_SCAN_ALLOW_DEV_AGAINST_MINI=1` is explicitly set. This is a tripwire, not a policy: the user must opt in deliberately to a race-prone configuration.

2. **`.env.local` override pattern** — for actual local dev, create `.env.local` (gitignored) with `UW_SCAN_DB_HOST=127.0.0.1` and `UW_SCAN_DB_NAME=argon_dev` (matching local Postgres state). `scripts/dev.sh` loads `.env.local` after `.env` so its values win. Maintain a local Postgres with role `argon_app`/`argon_dev` and DB `argon_dev`/`argon_test` for the rare "test a destructive migration before promoting" case.

This is the equivalent of xenon's `DATABASE_URL_PAPER` fallback.

### 6.4 Worker race avoidance — explicit mechanism

The race condition is prevented at the `scripts/dev.sh` guard (above), not by SQL-layer enforcement. The chain:

- MacBook's default workflow runs no workers (editor-only)
- Running `scripts/dev.sh` is intentional, and the guard refuses unless the user is on `.env.local`-local-Postgres OR explicitly opted in
- Mini's workers are the only writers against `argon_dev` in normal operation
- Therefore the `FOR UPDATE SKIP LOCKED` queue has a single set of claimers

If the user opts in to `UW_SCAN_ALLOW_DEV_AGAINST_MINI=1` (e.g., to reproduce a bug observed in mini-state), they accept that test rows may get claimed by mini workers.

---

## 7. Backup and durability

The mini becomes the only host with `argon_dev` data. Three layers of backup:

1. **Time Machine** on the mini (assumed already configured for xenon)
2. **Nightly `pg_dump` to local disk**, retained 7 days. New 14th launchd plist `com.argon.backup`:
   ```xml
   <key>StartCalendarInterval</key>
   <dict><key>Hour</key><integer>3</integer><key>Minute</key><integer>0</integer></dict>
   <key>ProgramArguments</key>
   <array>
     <string>/bin/sh</string><string>-c</string>
     <string>pg_dump -Fc argon_dev | gzip > __PROJECT_DIR__/data/backups/argon_dev-$(date +\%F).dump.gz \
             &amp;&amp; find __PROJECT_DIR__/data/backups -name 'argon_dev-*.dump.gz' -mtime +7 -delete</string>
   </array>
   ```
3. **Weekly R2 upload** (Sundays 04:00) — already have R2 credentials in `.env`:
   ```
   aws s3 cp __PROJECT_DIR__/data/backups/argon_dev-$(date +%F).dump.gz \
             s3://uw-backups/postgres/ --endpoint-url $R2_ENDPOINT
   ```

If the mini's SSD fails: restore from latest R2 dump onto a new host, re-bootstrap. RPO ≤ 7 days for the off-machine case; ≤ 24 hours if Time Machine survives.

---

## 8. Rollback strategy

### 8.1 Per-deploy rollback (handled by `macmini-prod.sh`)

Xenon-style: record `git describe --tags --exact-match` before checkout; if any of the 13 services fail health, `git checkout <prev>`, rebuild, kickstart all, re-health-check. Same logic, longer service list.

### 8.2 Big-bang rollback (entire migration)

If the migration fails mid-cutover or the mini stack is unstable in the first 24-48 hours:

1. **MacBook DB is untouched** by `macmini-data-promote.sh` (it dumps, ships, restores onto the mini; the source is read-only during the operation). Point `.env` back at `localhost`, restart `scripts/dev.sh`, you are back to today's state.
2. **Stop and unload mini services**:
   ```
   ssh moremeds@100.66.147.98 'while read s; do
     launchctl bootout gui/$UID/$s 2>/dev/null || true
   done < ~/projects/unusual-whales/config/services.list'
   ```
3. **Drop mini DBs and role** (only if migration is fully abandoned):
   ```
   ssh moremeds@100.66.147.98 'psql postgres -c "
     DROP DATABASE IF EXISTS argon_dev;
     DROP DATABASE IF EXISTS argon_test;
     DROP ROLE IF EXISTS argon_app;"'
   ```
4. xenon is unaffected — different DBs, different roles, different launchd labels.

---

## 9. Observability

- **Per-service logs:** `~/projects/unusual-whales/logs/{api,web,massive-ws,worker-uw-0,...}.{out,err}.log` — same convention as xenon
- **Aggregate tail:** `ssh moremeds@100.66.147.98 'cd ~/projects/unusual-whales && tail -f logs/*.err.log'`
- **Health endpoint:** `GET http://127.0.0.1:8400/health` (already implemented; covers DB ping, worker heartbeats)
- **launchd status:** `ssh moremeds@100.66.147.98 'launchctl print gui/$UID/com.argon.worker.ai-claude-0'` for service-level inspection
- **Postgres metrics:** `pg_stat_activity`, `pg_stat_user_tables` queryable from MacBook over Tailscale
- **Console.app:** mini's `log stream --predicate 'process == "uvicorn"'` for raw macOS logs

No Grafana, no Prometheus — this is a single-user internal tool, the file-based logs + health endpoint suffice.

---

## 10. Open items deferred to implementation plan

- Exact `npm run build` standalone-output layout (Next.js 16 quirk — copy `static/` and `public/` into standalone dir as a post-build step)
- `macmini-deploy-branch.sh` wrapper script details (whether to default to `--rebuild-web` vs Python-only fast path)
- Whether `argon_test` gets a dedicated test data fixture or starts empty (likely empty — `pytest-postgresql` creates ephemeral DBs anyway for unit tests; `argon_test` is for the few tests that need a persistent target)
- launchd `StartInterval` for `com.argon.backup` — picking 03:00 here; verify no overlap with xenon's nightly jobs
- Whether the `scripts/deploy/macmini-deploy-branch.sh` wrapper lives in argon's repo or in a personal `~/bin/` (probably in the repo for portability)

---

## 11. Migration order (high-level — full plan goes in `writing-plans` next)

Six phases, sequenced so the runtime is always functional: mini infra prepared first, cutover happens with **both** DBs alive (MacBook's `option_wizard` untouched throughout), MacBook switches over via env vars only, and cosmetic codebase rename comes last when it carries zero runtime risk.

| # | Phase | Type | Branch |
|---|---|---|---|
| 1 | **Repo scaffolding** — deploy scripts (`macmini-bootstrap.sh`, `macmini-prod.sh`, `macmini-data-promote.sh`), plist templates (`config/templates/com.argon.*.plist.template`), and `config/services.list`. All repo-only, no execution. Verified with `--dry-run` paths in each script. | PR | `feat/macmini-deploy-scaffolding` |
| 2 | **Mini bootstrap (manual run)** — execute `macmini-bootstrap.sh` on the mini as `moremeds`. Creates `argon_app` role (NOSUPERUSER, owner) and empty `argon_dev` + `argon_test` databases. Renders + loads all 13 launchd plists. Services start but `argon_dev` is empty, so workers idle / no-op politely. Verifies Claude CLI and Codex CLI are signed in for `moremeds`. | Host op (no PR) | n/a |
| 3 | **DB cutover** — run `macmini-data-promote.sh moremeds@100.66.147.98 --confirm` from MacBook. Refuses if MacBook writers are listening (ports 8400/3001 or `uw_scan.worker.*` processes). `pg_dump option_wizard` → ship over Tailscale → `pg_restore --clean --if-exists -d argon_dev` on mini. Mini services become healthy. MacBook's local `option_wizard` is **read but untouched** (rollback insurance — leave it running). | Host op (no PR) | n/a |
| 4 | **MacBook switch + dev.sh guard** — update MacBook `.env`: `UW_SCAN_DB_HOST=100.66.147.98`, `UW_SCAN_DB_NAME=argon_dev`, `UW_SCAN_DB_USER=argon_app`, `UW_SCAN_DB_PASSWORD=argon_dev`. Stop MacBook's `scripts/dev.sh` permanently in the normal workflow. Land the `scripts/dev.sh` guard from §6.3 (refuses to run against mini without `UW_SCAN_ALLOW_DEV_AGAINST_MINI=1` opt-in). After this phase, the mini is the source of truth at runtime even though source code still says `option_wizard` in fallback defaults / tests / docs (env vars carry the real value). | PR | `chore/macbook-point-at-mini` |
| 5 | **Codebase rename cleanup** — replace `option_wizard` → `argon_dev` and `option_wizard_test` → `argon_test` in the 17 live files (1 src/ default, 7 test fixtures, 1 script, 5 root docs, 3 active specs/plans). Update `.env.example` to default to `argon_dev`. Pure cosmetic — runtime is already on argon_dev via env vars. CI green against `argon_test` (the test DB created in phase 2) before merge. Archived docs left alone. | PR | `chore/rename-option-wizard-to-argon` |
| 6 | **Backup + ops hardening** — add `com.argon.backup` plist (nightly 03:00 `pg_dump | gzip` retained 7 days); set up weekly R2 upload (Sunday 04:00); document `macmini-prod.sh` rollback procedure in `docs/ops/`; verify a deliberately-broken deploy rolls back. | PR | `feat/macmini-backup-and-ops` |

**Revertability:**
- Phases 1, 5, 6 are pure repo changes — `git revert` is safe.
- Phase 2 (host state) is reverted by `launchctl bootout` for all `com.argon.*` and dropping the role/DBs (§8.2).
- Phase 3 (cutover) is reverted by ignoring the mini's data — MacBook's `option_wizard` is the unchanged source.
- Phase 4 (MacBook switch) is reverted by flipping `.env` back to `UW_SCAN_DB_HOST=127.0.0.1` and `UW_SCAN_DB_NAME=option_wizard` and re-running MacBook's `scripts/dev.sh`.

**Why this ordering avoids the trap in the original draft:**
- Original draft had codebase rename in phase 1. That breaks `scripts/dev.sh` on MacBook *during* the migration window because the code expects `argon_dev` but MacBook's local Postgres still has `option_wizard`. The fix here: keep code on `option_wizard` semantics until phase 4's `.env` switch makes runtime point at the (renamed) mini DB, then do the cosmetic rename in phase 5 when nothing depends on it.

---

## 12. Success criteria

- [ ] All 13 `com.argon.*` services running on the mini, `launchctl print` shows `state = running`
- [ ] MacBook `.env` `UW_SCAN_DB_HOST=100.66.147.98` and `scripts/dev.sh` is no longer invoked except for emergency local dev
- [ ] `curl http://100.66.147.98:3001` from MacBook returns the watchlist page (over Tailscale)
- [ ] `psql -h 100.66.147.98 -U argon_app argon_dev -c "SELECT COUNT(*) FROM uw_scan.scan_runs"` returns the same row count that was on the MacBook pre-cutover, ±0 rows (allow for any in-flight rows that landed mid-cutover and got lost)
- [ ] Closing the MacBook lid does NOT stop data collection (verified by checking `scan_runs` count increases over a multi-hour MacBook-asleep window)
- [ ] Nightly backup at 03:00 produces `data/backups/argon_dev-<date>.dump.gz` on the mini
- [ ] Rollback path verified: a deliberately-broken deploy via `macmini-prod.sh v0.0.0-broken` rolls back to the previous tag and services come back healthy
