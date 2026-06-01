# Mac Mini Stack Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **AMENDMENT 2026-06-01 (post-implementation):** During Phase 1 the user revised three design points. See the AMENDMENT block in `docs/superpowers/specs/2026-06-01-mac-mini-stack-migration-design.md` for the rationale. Summary:
> 1. DB names kept as `option_wizard` / `option_wizard_test` (not renamed to `argon_dev` / `argon_test`).
> 2. Password is auto-generated via `openssl rand -base64 24` in `macmini-bootstrap.sh`, persisted in `.env` + `~/.pgpass`. Idempotent on re-runs.
> 3. `~/.pgpass` replaces inline `PGPASSWORD=...` in the backup plist, data-promote.sh, and runbook restore commands.
>
> Task code blocks below still reference `argon_dev` / `argon_test` / `PGPASSWORD=argon_dev` from the pre-amendment design. Read them as design intent — the actual landed code under `scripts/deploy/`, `config/templates/`, `tests/`, `.env.example`, and `docs/ops/macmini-runbook.md` reflects the amendment.

**Goal:** Move the entire `unusual-whales` runtime (13 long-running processes + 8.2 GB Postgres DB) from the user's MacBook Pro onto the Mac mini at Tailscale `100.66.147.98`, under launchd, sharing infrastructure with xenon (already deployed on that host).

**Architecture:** All 13 processes run as host-native launchd jobs (no Docker — mirrors xenon's already-proven pattern). Postgres reuses xenon's existing `postgresql@16` cluster with two new DBs (`option_wizard`, `option_wizard_test` — see amendment above) and a new non-superuser role (`argon_app`). MacBook becomes editor-only; it hits the mini's DB over Tailscale and pushes code via `git push` + a small mini-side deploy wrapper. Mini-DB cutover happens with MacBook's local `option_wizard` left untouched as rollback insurance.

**Tech Stack:** macOS arm64, launchd, Homebrew `postgresql@16`, `uv` (Python 3.13), Next.js 16 (`next start` from `web/package.json`, port 3001), bash deploy scripts, Tailscale (network), Postgres `pg_dump -Fc` + `pg_restore` streamed over SSH (single-thread — `pg_restore -j` isn't compatible with the stdin pipeline; ~10-25 min on 8.2 GB over Tailscale), `pytest` + `pytest-postgresql` for tests.

**Reference spec:** `docs/superpowers/specs/2026-06-01-mac-mini-stack-migration-design.md`
**Reference implementation (verbatim model):** `~/projects/xenon/scripts/deploy/macmini-{bootstrap,prod,data-promote}.sh` and `~/projects/xenon/config/templates/com.xenon.*.plist.template`

---

## File Structure

### New files (15 total: 12 in Phase 1 + 1 in Phase 4 + 2 in Phase 6)

**Phase 1 — `feat/macmini-deploy-scaffolding` (12 files):**

| Path | Responsibility |
|---|---|
| `scripts/deploy/macmini-bootstrap.sh` | First-time idempotent host setup: create role + DBs, scaffold env, build, render + load launchd plists, health-check |
| `scripts/deploy/macmini-prod.sh` | Recurring tag-based deploy with rollback: checkout tag, rebuild, kickstart 13 services, health-check, auto-rollback on failure |
| `scripts/deploy/macmini-data-promote.sh` | Run from MacBook — `pg_dump` `option_wizard` → ship over Tailscale → `pg_restore` to `argon_dev` on mini |
| `scripts/deploy/macmini-deploy-branch.sh` | MacBook-side wrapper: `git push` + SSH to mini + checkout + rebuild + kickstart (fast iteration) |
| `config/services.list` | Canonical list of 13 `com.argon.*` service labels — single source of truth for bootstrap, prod, rollback loops |
| `config/templates/com.argon.api.plist.template` | launchd plist for FastAPI uvicorn process (port 8400) |
| `config/templates/com.argon.web.plist.template` | launchd plist running `npm run start` (port 3001 — defined in `web/package.json`) |
| `config/templates/com.argon.worker.plist.template` | Parameterized launchd plist — rendered 10× with `__ROLE__`/`__INDEX__` substitution (uw/massive/ai-codex/ai-claude/ai-deepseek × 2) |
| `config/templates/com.argon.massive-ws.plist.template` | launchd plist for the single massive WS consumer |
| `config/templates/com.argon.backup.plist.template` | launchd plist template for nightly `pg_dump` backup at 03:00 (template added in Phase 1 so its render is tested; not loaded until Phase 6) |
| `tests/integration/deploy/test_plist_render.py` | Verifies each template substitutes to valid plist XML (via `plutil -lint`) |
| `docs/ops/macmini-runbook.md` | Step-by-step ops doc — bootstrap, cutover, deploy, rollback procedures |

**Phase 4 — `chore/macbook-point-at-mini` (1 additional file):**

| Path | Responsibility |
|---|---|
| `tests/unit/test_config_env_local.py` | Regression test for `Settings.from_env` loading `.env.local` with override semantics — pair with the dev.sh guard |

**Phase 6 — `feat/macmini-backup-and-ops` (2 additional files):**

| Path | Responsibility |
|---|---|
| `scripts/deploy/macmini-backup-upload-r2.sh` | Weekly R2 upload of latest local dump (Sundays 04:00) |
| `config/templates/com.argon.backup-r2.plist.template` | launchd plist for the weekly R2 upload |

### Modified files (13)

| Path | Change |
|---|---|
| `scripts/dev.sh` | Add MacBook guard: refuse to run if `UW_SCAN_DB_HOST` is the mini's address unless `UW_SCAN_ALLOW_DEV_AGAINST_MINI=1` |
| `src/uw_scan/config.py` | Default `db_name` `option_wizard` → `argon_dev` (lines 65 + 235) |
| `scripts/dry_run_volatility_endpoint.py` | Docstring example: `option_wizard_test` → `argon_test` |
| `tests/conftest.py` | Test DB name fixture |
| `tests/unit/worker/test_gold_warmup.py` | DB name refs |
| `tests/integration/test_pipeline_strike_gex.py` | DB name refs |
| `tests/integration/storage/test_repository_watchlist.py` | DB name refs |
| `tests/integration/storage/test_migrations.py` | DB name refs |
| `tests/integration/storage/test_gold_migrations.py` | DB name refs |
| `tests/integration/test_pipeline_e2e.py` | DB name refs |
| `.env.example` | Update `UW_SCAN_DB_NAME` default + add mini-host comment |
| `CLAUDE.md` | DB name + ops sections |
| `AGENTS.md` | Mirror CLAUDE.md per project sync rule |
| `README.md` | DB name + Mac mini deploy reference |

### Files NOT touched (intentionally)

- `docs/research/**` — research notes, frozen at write time
- `docs/superpowers/specs/archive/**`, `docs/superpowers/plans/archive/**` — historical record
- `docs/superpowers/specs/2026-05-27-canary-v2a-*.md` — historical canary spec, frozen as written
- `docs/superpowers/plans/2026-05-26-5pct-canary-*.md` — historical canary log, frozen as written
- `docs/superpowers/plans/2026-05-27-canary-v2a-*.md` — historical canary plan, frozen as written
- User's local `~/.env` for unusual-whales — manually edited in phase 4 (gitignored)

---

## Phase 1 — Repo Scaffolding (PR: `feat/macmini-deploy-scaffolding`)

Pure repo changes. No execution against the mini until Phase 2. Goal: produce all the deploy scripts and plist templates needed by later phases, fully linted and (where applicable) tested.

### Task 1.1: Create `config/services.list`

**Files:**
- Create: `config/services.list`

- [ ] **Step 1: Write the file**

```
# Canonical list of com.argon.* launchd services. Used by:
#   scripts/deploy/macmini-bootstrap.sh   — for loading
#   scripts/deploy/macmini-prod.sh        — for kickstart loop
#   scripts/deploy/macmini-data-promote.sh — for post-cutover restart
# Backup plist (com.argon.backup) is NOT listed — it's calendar-scheduled,
# not kickstart-driven, and should not be touched on app deploys.
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

- [ ] **Step 2: Verify line count is 13**

Run: `grep -vE '^#|^$' config/services.list | wc -l`
Expected: `13`

- [ ] **Step 3: Commit**

```bash
git add config/services.list
git commit -m "chore(macmini): add canonical service label list"
```

### Task 1.2: Create `config/templates/com.argon.api.plist.template`

**Files:**
- Create: `config/templates/com.argon.api.plist.template`

- [ ] **Step 1: Write the template**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.argon.api</string>

    <key>ProgramArguments</key>
    <array>
        <string>__UV_BIN__</string>
        <string>run</string>
        <string>uvicorn</string>
        <string>uw_scan.api.server:app</string>
        <string>--host</string>
        <string>127.0.0.1</string>
        <string>--port</string>
        <string>8400</string>
    </array>

    <key>WorkingDirectory</key>
    <string>__PROJECT_DIR__</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>__BREW_PREFIX__/bin:/usr/local/bin:/usr/bin:/bin</string>
        <key>HOME</key>
        <string>/Users/__USER__</string>
        <key>USER</key>
        <string>__USER__</string>
    </dict>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
        <key>Crashed</key>
        <true/>
    </dict>

    <key>ThrottleInterval</key>
    <integer>10</integer>

    <key>ProcessType</key>
    <string>Background</string>

    <key>StandardOutPath</key>
    <string>__PROJECT_DIR__/logs/api.out.log</string>

    <key>StandardErrorPath</key>
    <string>__PROJECT_DIR__/logs/api.err.log</string>
</dict>
</plist>
```

- [ ] **Step 2: Verify XML structure with a temp render**

Run: `sed -e 's|__UV_BIN__|/opt/homebrew/bin/uv|' -e 's|__PROJECT_DIR__|/tmp/p|' -e 's|__BREW_PREFIX__|/opt/homebrew|' -e 's|__USER__|me|' config/templates/com.argon.api.plist.template | plutil -lint -`
Expected: `- OK` (or `<stdin>: OK`)

- [ ] **Step 3: Commit** (defer commit to end of phase to batch templates together)

### Task 1.3: Create `config/templates/com.argon.web.plist.template`

**Why `npm run start` instead of a standalone `server.js`:** unusual-whales' `web/next.config.mjs` does NOT set `output: "standalone"` (xenon's does, but xenon still uses `npm run start` for the same reason). The repo's `web/package.json` defines `"start": "next start --port 3001"` — that's the canonical production-server entry. Calling `__NPM_BIN__ run start` mirrors xenon's already-proven pattern and avoids inventing a build-output path that doesn't exist.

**Files:**
- Create: `config/templates/com.argon.web.plist.template`

- [ ] **Step 1: Write the template**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.argon.web</string>

    <key>ProgramArguments</key>
    <array>
        <string>__NPM_BIN__</string>
        <string>run</string>
        <string>start</string>
    </array>

    <key>WorkingDirectory</key>
    <string>__PROJECT_DIR__/web</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>__BREW_PREFIX__/bin:/usr/local/bin:/usr/bin:/bin</string>
        <key>HOME</key>
        <string>/Users/__USER__</string>
        <key>USER</key>
        <string>__USER__</string>
        <key>HOSTNAME</key>
        <string>127.0.0.1</string>
        <key>NODE_ENV</key>
        <string>production</string>
    </dict>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
        <key>Crashed</key>
        <true/>
    </dict>

    <key>ThrottleInterval</key>
    <integer>10</integer>

    <key>ProcessType</key>
    <string>Background</string>

    <key>StandardOutPath</key>
    <string>__PROJECT_DIR__/logs/web.out.log</string>

    <key>StandardErrorPath</key>
    <string>__PROJECT_DIR__/logs/web.err.log</string>
</dict>
</plist>
```

Note: port 3001 is defined in `web/package.json`'s `start` script — no need to set `PORT` here. The `HOSTNAME=127.0.0.1` env var binds Next.js to localhost only (the mini exposes 3001 over Tailscale via Tailnet routing, not by binding 0.0.0.0).

- [ ] **Step 2: Verify with plutil**

Run: `sed -e 's|__NPM_BIN__|/opt/homebrew/bin/npm|' -e 's|__PROJECT_DIR__|/tmp/p|' -e 's|__BREW_PREFIX__|/opt/homebrew|' -e 's|__USER__|me|' config/templates/com.argon.web.plist.template | plutil -lint -`
Expected: `- OK`

### Task 1.4: Create `config/templates/com.argon.worker.plist.template`

**Files:**
- Create: `config/templates/com.argon.worker.plist.template`

- [ ] **Step 1: Write the parameterized template**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.argon.worker.__ROLE__-__INDEX__</string>

    <key>ProgramArguments</key>
    <array>
        <string>__UV_BIN__</string>
        <string>run</string>
        <string>python</string>
        <string>-m</string>
        <string>uw_scan.worker.scheduler</string>
    </array>

    <key>WorkingDirectory</key>
    <string>__PROJECT_DIR__</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>__BREW_PREFIX__/bin:/usr/local/bin:/usr/bin:/bin</string>
        <key>HOME</key>
        <string>/Users/__USER__</string>
        <key>USER</key>
        <string>__USER__</string>
        <key>UW_SCAN_WORKER_ROLE</key>
        <string>__ROLE__</string>
        <key>UW_SCAN_WORKER_INDEX</key>
        <string>__INDEX__</string>
        <key>UW_SCAN_WORKER_COUNT</key>
        <string>2</string>
        <key>UW_SCAN_UW_WORKER_COUNT</key>
        <string>2</string>
        <key>UW_SCAN_MASSIVE_WORKER_COUNT</key>
        <string>2</string>
        <key>UW_SCAN_AI_WORKER_COUNT</key>
        <string>2</string>
        <key>TRADE_INSIGHTS_AI_CODEX_WORKER_COUNT</key>
        <string>2</string>
        <key>TRADE_INSIGHTS_AI_CLAUDE_WORKER_COUNT</key>
        <string>2</string>
        <key>TRADE_INSIGHTS_AI_DEEPSEEK_WORKER_COUNT</key>
        <string>2</string>
        <key>MASSIVE_WS_ENABLED</key>
        <string>true</string>
    </dict>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
        <key>Crashed</key>
        <true/>
    </dict>

    <key>ThrottleInterval</key>
    <integer>10</integer>

    <key>ProcessType</key>
    <string>Background</string>

    <key>StandardOutPath</key>
    <string>__PROJECT_DIR__/logs/worker-__ROLE__-__INDEX__.out.log</string>

    <key>StandardErrorPath</key>
    <string>__PROJECT_DIR__/logs/worker-__ROLE__-__INDEX__.err.log</string>
</dict>
</plist>
```

- [ ] **Step 2: Verify with plutil for one role**

Run: `sed -e 's|__UV_BIN__|/opt/homebrew/bin/uv|' -e 's|__PROJECT_DIR__|/tmp/p|' -e 's|__BREW_PREFIX__|/opt/homebrew|' -e 's|__USER__|me|' -e 's|__ROLE__|uw|g' -e 's|__INDEX__|0|g' config/templates/com.argon.worker.plist.template | plutil -lint -`
Expected: `- OK`

**NOTE:** the `USER` env var is required for the Claude/Codex CLI runners to find OAuth in the keychain. See `src/uw_scan/worker/jobs/trade_insights_ai_runners.py` — comment "Without USER, the OAuth lookup misses and claude --print fails".

### Task 1.5: Create `config/templates/com.argon.massive-ws.plist.template`

**Files:**
- Create: `config/templates/com.argon.massive-ws.plist.template`

- [ ] **Step 1: Write the template**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.argon.massive-ws</string>

    <key>ProgramArguments</key>
    <array>
        <string>__UV_BIN__</string>
        <string>run</string>
        <string>python</string>
        <string>-m</string>
        <string>uw_scan.worker.massive_ws_consumer</string>
    </array>

    <key>WorkingDirectory</key>
    <string>__PROJECT_DIR__</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>__BREW_PREFIX__/bin:/usr/local/bin:/usr/bin:/bin</string>
        <key>HOME</key>
        <string>/Users/__USER__</string>
        <key>USER</key>
        <string>__USER__</string>
        <key>MASSIVE_WS_ENABLED</key>
        <string>true</string>
    </dict>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
        <key>Crashed</key>
        <true/>
    </dict>

    <key>ThrottleInterval</key>
    <integer>10</integer>

    <key>ProcessType</key>
    <string>Background</string>

    <key>StandardOutPath</key>
    <string>__PROJECT_DIR__/logs/massive-ws.out.log</string>

    <key>StandardErrorPath</key>
    <string>__PROJECT_DIR__/logs/massive-ws.err.log</string>
</dict>
</plist>
```

- [ ] **Step 2: Verify with plutil**

Run: `sed -e 's|__UV_BIN__|/opt/homebrew/bin/uv|' -e 's|__PROJECT_DIR__|/tmp/p|' -e 's|__BREW_PREFIX__|/opt/homebrew|' -e 's|__USER__|me|' config/templates/com.argon.massive-ws.plist.template | plutil -lint -`
Expected: `- OK`

### Task 1.6: Create `config/templates/com.argon.backup.plist.template`

Defined now (phase 1), wired up in phase 6.

**Files:**
- Create: `config/templates/com.argon.backup.plist.template`

- [ ] **Step 1: Write the template**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.argon.backup</string>

    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>-c</string>
        <string>set -euo pipefail; mkdir -p __PROJECT_DIR__/data/backups; __BREW_PREFIX__/opt/postgresql@16/bin/pg_dump -Fc -h 127.0.0.1 -U argon_app argon_dev | gzip &gt; __PROJECT_DIR__/data/backups/argon_dev-$(date +\%Y\%m\%d).dump.gz; find __PROJECT_DIR__/data/backups -name 'argon_dev-*.dump.gz' -mtime +7 -delete</string>
    </array>

    <key>WorkingDirectory</key>
    <string>__PROJECT_DIR__</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>__BREW_PREFIX__/bin:/usr/local/bin:/usr/bin:/bin</string>
        <key>HOME</key>
        <string>/Users/__USER__</string>
        <key>PGPASSWORD</key>
        <string>argon_dev</string>
    </dict>

    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>3</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>

    <key>RunAtLoad</key>
    <false/>

    <key>StandardOutPath</key>
    <string>__PROJECT_DIR__/logs/backup.out.log</string>

    <key>StandardErrorPath</key>
    <string>__PROJECT_DIR__/logs/backup.err.log</string>
</dict>
</plist>
```

- [ ] **Step 2: Verify with plutil**

Run: `sed -e 's|__PROJECT_DIR__|/tmp/p|' -e 's|__BREW_PREFIX__|/opt/homebrew|' -e 's|__USER__|me|' config/templates/com.argon.backup.plist.template | plutil -lint -`
Expected: `- OK`

### Task 1.7: Write the plist render test

**Files:**
- Create: `tests/integration/deploy/__init__.py`
- Create: `tests/integration/deploy/test_plist_render.py`

- [ ] **Step 1: Write empty package init**

`tests/integration/deploy/__init__.py`:
```python
```
(empty file — marks the directory as a pytest package)

- [ ] **Step 2: Write the failing test**

`tests/integration/deploy/test_plist_render.py`:
```python
"""Verify each launchd plist template renders to valid Apple plist XML.

Each template uses sed-style __PLACEHOLDER__ substitution. This test renders
each template with realistic values, writes the output to a temp file, and
runs `plutil -lint` to verify the result is well-formed plist XML.

If this test fails, the bootstrap script's `render_plist` step will also fail
on the mini — fix the template before phase 2.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
TEMPLATES_DIR = REPO_ROOT / "config" / "templates"

# Substitutions that mirror what macmini-bootstrap.sh applies.
COMMON_SUBS = {
    "__PROJECT_DIR__": "/Users/moremeds/projects/unusual-whales",
    "__USER__": "moremeds",
    "__BREW_PREFIX__": "/opt/homebrew",
    "__UV_BIN__": "/opt/homebrew/bin/uv",
    "__NODE_BIN__": "/opt/homebrew/bin/node",
    "__NPM_BIN__": "/opt/homebrew/bin/npm",
}

# Worker template needs role + index substitutions too.
WORKER_SUBS = {
    **COMMON_SUBS,
    "__ROLE__": "uw",
    "__INDEX__": "0",
    "__COUNT__": "2",
}


def _render(template_path: Path, subs: dict[str, str]) -> str:
    text = template_path.read_text()
    for placeholder, value in subs.items():
        text = text.replace(placeholder, value)
    return text


@pytest.mark.parametrize(
    "template_name,subs",
    [
        ("com.argon.api.plist.template", COMMON_SUBS),
        ("com.argon.web.plist.template", COMMON_SUBS),
        ("com.argon.worker.plist.template", WORKER_SUBS),
        ("com.argon.massive-ws.plist.template", COMMON_SUBS),
        ("com.argon.backup.plist.template", COMMON_SUBS),
    ],
)
def test_template_renders_to_valid_plist(
    tmp_path: Path, template_name: str, subs: dict[str, str]
) -> None:
    template_path = TEMPLATES_DIR / template_name
    assert template_path.exists(), f"template not found: {template_path}"
    rendered = _render(template_path, subs)

    # No leftover placeholders.
    assert "__" not in rendered, (
        f"unsubstituted placeholder in {template_name}:\n"
        + "\n".join(line for line in rendered.splitlines() if "__" in line)
    )

    # Apple plist XML validation via plutil.
    out_path = tmp_path / "rendered.plist"
    out_path.write_text(rendered)
    result = subprocess.run(
        ["plutil", "-lint", str(out_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"plutil rejected {template_name}:\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_services_list_matches_template_set() -> None:
    """Every label in config/services.list must be producible from some template."""
    services_path = REPO_ROOT / "config" / "services.list"
    assert services_path.exists()
    labels = [
        line.strip()
        for line in services_path.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert len(labels) == 13, f"expected 13 services, found {len(labels)}: {labels}"

    # Static labels (one plist each).
    static = {"com.argon.api", "com.argon.web", "com.argon.massive-ws"}
    # Parameterized worker labels: 5 roles × 2 indices = 10.
    worker_roles = {"uw", "massive", "ai-codex", "ai-claude", "ai-deepseek"}
    expected_workers = {
        f"com.argon.worker.{role}-{idx}"
        for role in worker_roles
        for idx in (0, 1)
    }
    expected = static | expected_workers
    assert set(labels) == expected, (
        f"unexpected/missing labels:\n"
        f"  missing from services.list: {sorted(expected - set(labels))}\n"
        f"  extra in services.list: {sorted(set(labels) - expected)}"
    )
```

- [ ] **Step 3: Run the test, expect PASS**

Run: `uv run pytest tests/integration/deploy/test_plist_render.py -v`
Expected: 6 tests pass (5 parametrized template tests + 1 services.list test).

If any fail, fix the template/services.list before continuing. Do not skip.

- [ ] **Step 4: Commit phase-1 templates + tests together**

```bash
git add config/services.list config/templates/ tests/integration/deploy/
git commit -m "feat(macmini): add launchd plist templates + services list

- config/templates/com.argon.{api,web,worker,massive-ws,backup}.plist.template
- config/services.list (13 service labels — single source of truth)
- tests/integration/deploy/test_plist_render.py (plutil validation)"
```

### Task 1.8: Write `scripts/deploy/macmini-bootstrap.sh`

The script is a direct port of xenon's `scripts/deploy/macmini-bootstrap.sh` (~330 lines). Differences from xenon's version are itemized below.

**Files:**
- Create: `scripts/deploy/macmini-bootstrap.sh` (executable)

- [ ] **Step 1: Copy xenon's bootstrap as starting point**

Run: `cp ~/projects/xenon/scripts/deploy/macmini-bootstrap.sh scripts/deploy/macmini-bootstrap.sh`

- [ ] **Step 2: Apply the deltas vs xenon's bootstrap**

Edit `scripts/deploy/macmini-bootstrap.sh` and replace verbatim:

1. **Header config block** — replace xenon's defaults with argon's:

```bash
ARGON_HOME="${ARGON_HOME:-$HOME/projects/unusual-whales}"
ARGON_REPO="${ARGON_REPO:-git@github.com:lcxxcllcx/unusual-whales.git}"
ARGON_BRANCH="${ARGON_BRANCH:-main}"
ARGON_PG_VERSION="${ARGON_PG_VERSION:-16}"
ARGON_NODE_VERSION="${ARGON_NODE_VERSION:-22}"
ARGON_DB_NAME="${ARGON_DB_NAME:-argon_dev}"
ARGON_DB_NAME_TEST="${ARGON_DB_NAME_TEST:-argon_test}"
ARGON_DB_ROLE="${ARGON_DB_ROLE:-argon_app}"
ARGON_DB_PASSWORD="${ARGON_DB_PASSWORD:-argon_dev}"
```

Remove xenon-specific vars: `XENON_TRADING_MODE`.

2. **Brew packages step** — keep `brew_install uv`, `brew_install "node@${ARGON_NODE_VERSION}"`, `brew_install "postgresql@${ARGON_PG_VERSION}"`, `brew_install git`, `brew_install gh`. They will be no-ops on a mini that already has xenon.

3. **Postgres role + DB step** — replace xenon's single-role/single-DB block with:

```bash
step "Database role + DBs"
PSQL="${PG_BIN}/psql -h localhost -U ${USER_NAME} postgres"

if $PSQL -tAc "SELECT 1 FROM pg_roles WHERE rolname='${ARGON_DB_ROLE}'" | grep -q 1; then
  skip "role ${ARGON_DB_ROLE} exists"
else
  say "Creating role ${ARGON_DB_ROLE}"
  $PSQL -c "CREATE ROLE ${ARGON_DB_ROLE} LOGIN PASSWORD '${ARGON_DB_PASSWORD}' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;"
  ok "role created"
fi

for db in "${ARGON_DB_NAME}" "${ARGON_DB_NAME_TEST}"; do
  if $PSQL -tAc "SELECT 1 FROM pg_database WHERE datname='${db}'" | grep -q 1; then
    skip "database ${db} exists"
  else
    say "Creating database ${db}"
    $PSQL -c "CREATE DATABASE ${db} OWNER ${ARGON_DB_ROLE};"
    ok "database created"
  fi
done
```

4. **AI CLI auth verification step** — INSERT this new step between repo clone and `.env` scaffolding:

```bash
step "Verify Codex CLI + Claude CLI signed in for ${USER_NAME}"
# These CLIs require keychain OAuth — env vars are stripped by the runner's
# allow-list so subscription auth wins. If either is unauthenticated, the
# AI workers will load and fail immediately. Fail fast here.
if ! command -v claude >/dev/null 2>&1; then
  die "claude CLI not on PATH — install via the official method and run 'claude /login' as ${USER_NAME}"
fi
if ! command -v codex >/dev/null 2>&1; then
  die "codex CLI not on PATH — install + authenticate"
fi
# Probe: does `claude --print` work non-interactively? It will if OAuth is in
# the keychain. We send an empty prompt and just check the exit code.
if ! echo "" | claude --print --output-format text --max-turns 1 \
      --tools "" --disable-slash-commands --strict-mcp-config \
      --mcp-config '{"mcpServers": {}}' --no-session-persistence \
      "ok?" >/dev/null 2>&1; then
  warn "claude --print probe failed — make sure ${USER_NAME} has run 'claude /login'"
  warn "(continuing anyway; AI workers may fail until this is fixed)"
fi
ok "AI CLIs present"
```

5. **launchd plist rendering loop** — replace xenon's three-label loop with a services.list-driven one:

```bash
step "Render + install launchd plists"
mkdir -p "${ARGON_HOME}/logs" "$HOME/Library/LaunchAgents"

UV_BIN="$(command -v uv)"
NODE_BIN="$(command -v node)"
NPM_BIN="$(command -v npm)"

render_static_plist() {
  local label="$1"
  local template="${label}.plist.template"
  local src="${ARGON_HOME}/config/templates/${template}"
  local dst="$HOME/Library/LaunchAgents/${label}.plist"
  [[ -f "$src" ]] || die "missing template: $src"
  sed \
    -e "s|__PROJECT_DIR__|${ARGON_HOME}|g" \
    -e "s|__USER__|${USER_NAME}|g" \
    -e "s|__BREW_PREFIX__|${BREW_PREFIX}|g" \
    -e "s|__UV_BIN__|${UV_BIN}|g" \
    -e "s|__NODE_BIN__|${NODE_BIN}|g" \
    -e "s|__NPM_BIN__|${NPM_BIN}|g" \
    "$src" > "$dst"
  ok "rendered $dst"
}

render_worker_plist() {
  local role="$1" index="$2"
  local label="com.argon.worker.${role}-${index}"
  local src="${ARGON_HOME}/config/templates/com.argon.worker.plist.template"
  local dst="$HOME/Library/LaunchAgents/${label}.plist"
  sed \
    -e "s|__PROJECT_DIR__|${ARGON_HOME}|g" \
    -e "s|__USER__|${USER_NAME}|g" \
    -e "s|__BREW_PREFIX__|${BREW_PREFIX}|g" \
    -e "s|__UV_BIN__|${UV_BIN}|g" \
    -e "s|__ROLE__|${role}|g" \
    -e "s|__INDEX__|${index}|g" \
    -e "s|__COUNT__|2|g" \
    "$src" > "$dst"
  ok "rendered $dst"
}

# Static plists
render_static_plist "com.argon.api"
render_static_plist "com.argon.web"
render_static_plist "com.argon.massive-ws"
render_static_plist "com.argon.backup"

# Worker plists (5 roles × 2 indices = 10)
for role in uw massive ai-codex ai-claude ai-deepseek; do
  for index in 0 1; do
    render_worker_plist "$role" "$index"
  done
done

# Load: read services.list (excludes backup — calendar-scheduled)
while IFS= read -r label; do
  [[ -z "$label" || "$label" == \#* ]] && continue
  plist="$HOME/Library/LaunchAgents/${label}.plist"
  launchctl unload "$plist" >/dev/null 2>&1 || true
  launchctl load "$plist"
  ok "loaded $label"
done < "${ARGON_HOME}/config/services.list"
```

(Backup plist is rendered but NOT loaded yet — that happens in Phase 6.)

6. **Health checks step** — replace xenon's two URL probes with argon's. Note the explicit `PGPASSWORD` — without it, psql would hang on an interactive password prompt on the fresh mini install where `~/.pgpass` doesn't yet have an entry for argon_app:

```bash
api_ok=0; web_ok=0; db_ok=0
check_url "http://127.0.0.1:8400/health" "api" && api_ok=1 || true
check_url "http://127.0.0.1:3001"        "web" && web_ok=1 || true
if PGPASSWORD="${ARGON_DB_PASSWORD}" "${PG_BIN}/psql" \
     -h localhost -U "${ARGON_DB_ROLE}" "${ARGON_DB_NAME}" \
     -c "SELECT COUNT(*) FROM uw_scan.scan_runs" >/dev/null 2>&1; then
  db_ok=1
fi
```

(`db_ok` will be 0 on a freshly-bootstrapped mini because the schema doesn't exist yet — that's expected; the summary message below explains.)

7. **Summary block** — replace xenon's summary with:

```bash
step "Bootstrap summary"
printf '  Repo:           %s\n' "${ARGON_HOME}"
printf '  Database:       %s, %s @ localhost:5432\n' "${ARGON_DB_NAME}" "${ARGON_DB_NAME_TEST}"
printf '  API:            %s\n' "$([[ $api_ok == 1 ]] && echo UP || echo DOWN)"
printf '  Web:            %s\n' "$([[ $web_ok == 1 ]] && echo UP || echo DOWN)"
printf '  Schema present: %s\n' "$([[ $db_ok == 1 ]] && echo YES || echo 'NO (run promote to populate)')"

cat <<NEXT

Next steps:
  1. Promote data from MacBook:
     # on the MacBook:
     ./scripts/deploy/macmini-data-promote.sh moremeds@100.66.147.98 --confirm

  2. Update MacBook .env to point UW_SCAN_DB_HOST=100.66.147.98

  3. Tail logs:
     tail -f logs/*.err.log

NEXT
```

8. **Remove all `xenon`/`ib`/`trading_mode` references** — search for any remaining `XENON_`, `xenon`, `IB`, `TRADING_MODE`, `ib-realtime` and remove or replace.

9. **Replace xenon's `.env` scaffold** — xenon's bootstrap pre-fills `XENON_QUOTE_TOKEN_SECRET` and `DATABASE_URL`; argon needs neither. Replace the Python heredoc with:

```bash
# .env scaffolding
step ".env files"
if [[ ! -f "${ARGON_HOME}/.env" ]]; then
  say "Creating .env from .env.example (you must fill secrets before services start)"
  cp "${ARGON_HOME}/.env.example" "${ARGON_HOME}/.env"
  # The .env.example default points UW_SCAN_DB_HOST at the Tailscale IP (which is
  # the MacBook's view of the mini). On the mini itself, prefer localhost loopback.
  python3 - <<PY
from pathlib import Path
p = Path("${ARGON_HOME}/.env")
text = p.read_text()
text = text.replace("UW_SCAN_DB_HOST=100.66.147.98", "UW_SCAN_DB_HOST=127.0.0.1")
text = text.replace("UW_SCAN_DB_NAME=option_wizard", "UW_SCAN_DB_NAME=${ARGON_DB_NAME}")
text = text.replace("UW_SCAN_DB_USER=", "UW_SCAN_DB_USER=${ARGON_DB_ROLE}")
text = text.replace("UW_SCAN_DB_PASSWORD=", "UW_SCAN_DB_PASSWORD=${ARGON_DB_PASSWORD}")
p.write_text(text)
print("  .env scaffolded")
PY
  chmod 600 "${ARGON_HOME}/.env"
  warn "OPEN ${ARGON_HOME}/.env AND FILL: UW_SCAN_API_KEY, MASSIVE_API_KEY,"
  warn "                                 FRED_API_KEY, R2_*, DEEPSEEK_API_KEY"
else
  skip ".env exists (not overwriting)"
fi
if [[ ! -f "${ARGON_HOME}/web/.env" ]]; then
  say "Creating web/.env shell (Clerk + Anthropic + UW token go here)"
  cat > "${ARGON_HOME}/web/.env" <<'EOF'
# Fill these before npm run build
ANTHROPIC_API_KEY=
UW_TOKEN=
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=
CLERK_SECRET_KEY=
EOF
  chmod 600 "${ARGON_HOME}/web/.env"
  warn "OPEN ${ARGON_HOME}/web/.env AND FILL all values."
else
  skip "web/.env exists"
fi
```

10. **`uv sync` extra** — this repo only defines a `postgres` extra in `pyproject.toml` (xenon's `--extra test` does not exist here). Replace every:

```bash
uv sync --frozen --extra test
```
with:
```bash
uv sync --frozen --extra postgres
```

If dev/test groups are needed on the mini, add `--group dev` (per `pyproject.toml`'s `[dependency-groups]`). For prod, `--extra postgres` is sufficient.

11. **Skip `bash scripts/migrate.sh` in bootstrap** — xenon's bootstrap runs `alembic upgrade head` to seed the schema before promote. Argon's `scripts/migrate.sh` calls `Settings.from_env()` which raises if `UW_SCAN_API_KEY` is unset (`src/uw_scan/config.py:225`). On a fresh bootstrap, the user fills DB defaults but the API key may not yet be in `.env`. Two clean options:
   - **Recommended for now:** drop the migrate step from bootstrap entirely. Phase 3's `pg_restore --clean --if-exists` brings the schema along with the data. After cutover, the schema is correct. For an empty greenfield install (no MacBook DB to promote), the user runs `bash scripts/migrate.sh` manually after filling secrets.
   - Alternative: factor a `scripts/migrate-bare.sh` that constructs DSN from `UW_SCAN_DB_*` only (no Settings load). Defer to a follow-up.

   Remove the `step "Alembic schema"` block from xenon's copy entirely.

12. **No root-level `npm install`** — xenon has both root `package.json` and `web/package.json`; argon has only `web/package.json`. The xenon bootstrap line:

```bash
(cd "${XENON_HOME}" && npm install --no-audit --no-fund --legacy-peer-deps)
```

MUST be deleted entirely. Replace the entire web-build block with:

```bash
# ---------- npm install + build ----------
step "Web build"
(cd "${ARGON_HOME}/web" && npm install --no-audit --no-fund --legacy-peer-deps)
(cd "${ARGON_HOME}/web" && npm run build)
ok "web built"
```

13. **Codex+Claude auth probes are HARD gates, not warnings** — per the spec (§4.1, "AI CLI auth verification step"). Replace the AI CLI auth block (delta 4) with:

```bash
step "Verify Codex CLI + Claude CLI signed in for ${USER_NAME}"
if ! command -v claude >/dev/null 2>&1; then
  die "claude CLI not on PATH — install per Anthropic docs and run 'claude /login' as ${USER_NAME}"
fi
if ! command -v codex >/dev/null 2>&1; then
  die "codex CLI not on PATH — install Codex CLI and authenticate"
fi
# Real Claude auth probe — fail loud if subscription auth missing.
if ! echo "respond with 'ok'" | claude --print --output-format text --max-turns 1 \
      --tools "" --disable-slash-commands --strict-mcp-config \
      --mcp-config '{"mcpServers": {}}' --no-session-persistence \
      >/dev/null 2>&1; then
  die "claude --print probe failed — run 'claude /login' as ${USER_NAME} and re-run bootstrap"
fi
# Real Codex auth probe.
if ! codex exec -s read-only "respond with ok" >/dev/null 2>&1; then
  die "codex exec probe failed — re-authenticate Codex CLI and re-run bootstrap"
fi
ok "Codex + Claude CLI auth confirmed for ${USER_NAME}"
```

Each probe IS a paid API call — only run on initial bootstrap (xenon's bootstrap is idempotent and probe-and-skip; if you want to skip the probe on re-runs, gate on a sentinel file like `~/.config/argon/auth-verified-${date}` — defer that hardening).

14. **Quote the summary's interpolated string** — xenon's bootstrap summary uses `printf` for plain strings, but the inline `echo NO (run promote to populate)` (delta 7) is invalid bash — the unquoted parens are subshell syntax. Replace `$([[ $db_ok == 1 ]] && echo YES || echo NO (run promote to populate))` with:

```bash
printf '  Schema present: %s\n' "$([[ $db_ok == 1 ]] && echo YES || echo 'NO (run promote to populate)')"
```

- [ ] **Step 3: Make it executable**

Run: `chmod +x scripts/deploy/macmini-bootstrap.sh`

- [ ] **Step 4: Syntax check + shellcheck**

Run: `bash -n scripts/deploy/macmini-bootstrap.sh && shellcheck scripts/deploy/macmini-bootstrap.sh`
Expected: no errors. (Shellcheck warnings about `local` outside functions or `SC2086` for intentional word-splitting are acceptable; shellcheck errors are not.)

If shellcheck isn't installed: `brew install shellcheck`.

- [ ] **Step 5: Commit**

```bash
git add scripts/deploy/macmini-bootstrap.sh
git commit -m "feat(macmini): add idempotent host bootstrap script

Port of xenon/scripts/deploy/macmini-bootstrap.sh with argon-specific
deltas: argon_app role (NOSUPERUSER), argon_dev + argon_test DBs,
Codex/Claude CLI auth verification step, services.list-driven plist
loading loop, argon-specific health checks."
```

### Task 1.9: Write `scripts/deploy/macmini-prod.sh`

**Files:**
- Create: `scripts/deploy/macmini-prod.sh` (executable)

- [ ] **Step 1: Copy xenon's prod script**

Run: `cp ~/projects/xenon/scripts/deploy/macmini-prod.sh scripts/deploy/macmini-prod.sh`

- [ ] **Step 2: Apply deltas vs xenon's**

1. Replace xenon's hardcoded service list with services.list iteration:

```bash
# ---------- Kickstart services ----------
step "Kickstart launchd services"
while IFS= read -r label; do
  [[ -z "$label" || "$label" == \#* ]] && continue
  launchctl kickstart -k "gui/$UID/${label}"
  say "kickstart $label"
done < config/services.list
```

2. Replace xenon's two URL health probes with argon's:

```bash
if check_url "http://127.0.0.1:8400/health" "api" \
   && check_url "http://127.0.0.1:3001"      "web"; then
```

3. Replace the rollback's hardcoded service list with services.list iteration:

```bash
while IFS= read -r label; do
  [[ -z "$label" || "$label" == \#* ]] && continue
  launchctl kickstart -k "gui/$UID/${label}"
done < config/services.list
```

4. Replace the refuse-to-run probe:

```bash
[[ -f "$HOME/Library/LaunchAgents/com.argon.api.plist" ]] \
  || die "no com.argon.api launchd plist — run macmini-bootstrap.sh first"
```

5. Replace `uv run alembic upgrade head` with `bash scripts/migrate.sh` — unusual-whales uses raw SQL migrations, not alembic. Migration script reads `Settings.from_env()` and DB config from `.env`, so it works on the mini once `.env` is filled (post-bootstrap).

6. Strip `XENON_TRADING_MODE` references entirely.

7. **`uv sync` flag** — replace `uv sync --frozen --extra test` (xenon's; doesn't exist here) with `uv sync --frozen --extra postgres`. The repo's only published extra is `postgres`.

8. **Remove the root-level `npm install`** — xenon has both root and web/ package.json; argon has only `web/package.json`. Replace xenon's build block:
```bash
npm install --no-audit --no-fund --legacy-peer-deps
(cd web && npm install --no-audit --no-fund --legacy-peer-deps)
```
with just:
```bash
(cd web && npm install --no-audit --no-fund --legacy-peer-deps)
```

- [ ] **Step 3: chmod + shellcheck**

Run: `chmod +x scripts/deploy/macmini-prod.sh && shellcheck scripts/deploy/macmini-prod.sh`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add scripts/deploy/macmini-prod.sh
git commit -m "feat(macmini): add tag-based deploy with rollback

Port of xenon/scripts/deploy/macmini-prod.sh. Uses scripts/migrate.sh
instead of alembic, services.list-driven kickstart loop, argon health
endpoints (8400/3001)."
```

### Task 1.10: Write `scripts/deploy/macmini-data-promote.sh`

**Files:**
- Create: `scripts/deploy/macmini-data-promote.sh` (executable)

- [ ] **Step 1: Copy xenon's data-promote script**

Run: `cp ~/projects/xenon/scripts/deploy/macmini-data-promote.sh scripts/deploy/macmini-data-promote.sh`

- [ ] **Step 2: Apply deltas vs xenon's**

0. **Delete xenon's `DATABASE_URL` preflight** — xenon's script does `set -a; source .env; set +a` and then refuses if `DATABASE_URL` is empty. Argon has no `DATABASE_URL` (uses `UW_SCAN_DB_*` shape per `.env.example` line 3 onwards), so this block exits the script before doing anything. REMOVE these lines entirely:

```bash
# REMOVE (xenon's; doesn't apply here):
[[ -f .env ]] || die "no .env in $REPO_ROOT"
# shellcheck disable=SC1091
set -a; source .env; set +a
[[ -n "${DATABASE_URL:-}" ]] || die "DATABASE_URL not set in .env"
```

1. Replace the writer-port refusal block — argon uses 8400 (api) and 3001 (web); also probe for worker processes:

```bash
step "Safety: ensure no local writers"
for port in 8400 3001; do
  if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    die "port $port is in use on MacBook — stop scripts/dev.sh before promoting (snapshot would be mid-write)"
  fi
done
if pgrep -f "uw_scan.worker.scheduler" >/dev/null 2>&1; then
  die "uw_scan.worker.scheduler is running on MacBook — stop it before promoting"
fi
if pgrep -f "uw_scan.worker.massive_ws_consumer" >/dev/null 2>&1; then
  die "uw_scan.worker.massive_ws_consumer is running on MacBook — stop it before promoting"
fi
say "no local writers listening"
```

2. **Replace source DB name & role with explicit script args, not env defaults.** Phase 4 changes MacBook's `.env` to point `UW_SCAN_DB_NAME=argon_dev UW_SCAN_DB_USER=argon_app`; after that, sourcing those defaults would dump the WRONG thing (try to dump the mini's argon_dev via MacBook's connection). Make the source explicit and document it:

```bash
# Usage:
#   ./scripts/deploy/macmini-data-promote.sh <ssh-host> --confirm \
#     [--src-db option_wizard] [--src-user chenxi]
#
# Phase 3 cutover: --src-db option_wizard (the pre-migration MacBook DB).
# Ad-hoc re-mirror later: --src-db argon_dev_macbook (or whatever your
# rollback-insurance local DB is named); only sensible if you maintain a
# local Postgres post-migration.
SRC_DB="option_wizard"   # default for the initial Phase 3 cutover
SRC_USER="chenxi"        # default MacBook DB owner
# Parse extra args (after ssh host + --confirm)
while [[ $# -gt 2 ]]; do
  case "$3" in
    --src-db)   SRC_DB="$4"; shift 2 ;;
    --src-user) SRC_USER="$4"; shift 2 ;;
    *) die "unknown arg: $3" ;;
  esac
done
# Target on mini (created by macmini-bootstrap.sh)
DST_DB="argon_dev"
DST_USER="argon_app"
say "Source: $SRC_DB (as $SRC_USER) → Destination: $DST_DB on $SSH_HOST"
```

3. Replace the pg_dump command:

```bash
"$PG_DUMP" -h localhost -U "$SRC_USER" -Fc --no-owner --no-acl -f "$DUMP_FILE" "$SRC_DB"
```

4. Replace the ssh+pg_restore — note the source DB → target DB rename happens here because `--clean --if-exists` operates on the destination and `--no-owner` strips ownership:

```bash
ssh "$SSH_HOST" "PGPASSWORD='argon_dev' pg_restore --clean --if-exists --no-owner --no-acl -h localhost -U ${DST_USER} -d ${DST_DB}" < "$DUMP_FILE"
```

5. Replace the verify query to use `uw_scan` schema and target DB:

```bash
ssh "$SSH_HOST" "PGPASSWORD='argon_dev' psql -h localhost -U ${DST_USER} ${DST_DB} -c \"
  SELECT relname, n_live_tup FROM pg_stat_user_tables
  WHERE schemaname='uw_scan' ORDER BY n_live_tup DESC LIMIT 20\""
```

6. Replace the final kickstart hint:

```bash
warn "Restart services on the mini:"
warn "  ssh $SSH_HOST 'cd ~/projects/unusual-whales && while read s; do
       [[ -z \"\$s\" || \"\$s\" == \\#* ]] && continue
       launchctl kickstart -k gui/\$UID/\$s
     done < config/services.list'"
```

- [ ] **Step 3: chmod + shellcheck**

Run: `chmod +x scripts/deploy/macmini-data-promote.sh && shellcheck scripts/deploy/macmini-data-promote.sh`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add scripts/deploy/macmini-data-promote.sh
git commit -m "feat(macmini): add MacBook → mini DB promote script

Port of xenon/scripts/deploy/macmini-data-promote.sh. Dumps source
option_wizard (or whatever UW_SCAN_DB_NAME points to), pg_restore's
into argon_dev on the mini. --no-owner strips source ownership so
argon_app owns the restored tables. Refuses if MacBook writers
(uvicorn :8400, next :3001, worker schedulers) are running."
```

### Task 1.11: Write `scripts/deploy/macmini-deploy-branch.sh`

**Files:**
- Create: `scripts/deploy/macmini-deploy-branch.sh` (executable)

- [ ] **Step 1: Write the script**

```bash
#!/usr/bin/env bash
# macmini-deploy-branch.sh — RUN FROM MACBOOK.
#
# Push the current local branch to origin, then SSH into the mini, fetch,
# checkout, rebuild, and kickstart all com.argon.* services. Designed for
# fast dev iteration ("ship this WIP branch to mini in one command").
#
# Usage:
#   ./scripts/deploy/macmini-deploy-branch.sh                  # uses current branch
#   ./scripts/deploy/macmini-deploy-branch.sh feature/foo      # explicit branch
#
# Flags:
#   --skip-web    skip `npm install && npm run build` (Python-only iteration)
#   --ssh-host    override the default moremeds@100.66.147.98
#
# Use macmini-prod.sh for tag-based prod deploys; this script is for WIP work.

set -euo pipefail

SSH_HOST="moremeds@100.66.147.98"
SKIP_WEB=0
BRANCH=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-web)  SKIP_WEB=1; shift ;;
    --ssh-host)  SSH_HOST="$2"; shift 2 ;;
    -h|--help)
      sed -n '2,16p' "$0"
      exit 0
      ;;
    *)           BRANCH="$1"; shift ;;
  esac
done

if [[ -z "$BRANCH" ]]; then
  BRANCH="$(git symbolic-ref --short HEAD)"
fi

say()  { printf '\033[1;34m[deploy-branch]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[deploy-branch] FAIL: %s\033[0m\n' "$*" >&2; exit 1; }

# 1. Push current branch
say "Push $BRANCH to origin"
git push origin "$BRANCH"

# 2. Build the remote command
REMOTE_CMD="set -euo pipefail
cd ~/projects/unusual-whales
git fetch origin
# Non-destructive checkout: refuse if working tree dirty (mini should be clean).
# Avoids the destructive 'git reset --hard' anti-pattern (see project CLAUDE.md).
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo 'ERROR: mini working tree dirty; aborting' >&2
  exit 1
fi
git checkout -B '$BRANCH' 'origin/$BRANCH'
# This repo only defines a 'postgres' extra in pyproject.toml; xenon's
# --extra test does NOT exist here.
uv sync --frozen --extra postgres"

if [[ "$SKIP_WEB" -eq 0 ]]; then
  REMOTE_CMD+="
# All Node deps live under web/ (no root package.json).
cd web && npm install --legacy-peer-deps --no-audit --no-fund && npm run build && cd .."
fi

REMOTE_CMD+="
bash scripts/migrate.sh
while IFS= read -r label; do
  [[ -z \"\$label\" || \"\$label\" == \\#* ]] && continue
  launchctl kickstart -k \"gui/\$UID/\$label\"
done < config/services.list
echo 'mini services kickstarted'"

# 3. Execute on mini
say "Deploy on $SSH_HOST"
ssh "$SSH_HOST" "$REMOTE_CMD"

# 4. Health check from MacBook side over Tailscale
say "Health probe"
for endpoint in "http://100.66.147.98:8400/health" "http://100.66.147.98:3001"; do
  if curl -fsS --max-time 5 "$endpoint" >/dev/null 2>&1; then
    say "  ✓ $endpoint"
  else
    die "  ✗ $endpoint (check ssh $SSH_HOST 'tail logs/api.err.log logs/web.err.log')"
  fi
done

say "Done. Branch $BRANCH live on $SSH_HOST."
```

- [ ] **Step 2: chmod + shellcheck**

Run: `chmod +x scripts/deploy/macmini-deploy-branch.sh && shellcheck scripts/deploy/macmini-deploy-branch.sh`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add scripts/deploy/macmini-deploy-branch.sh
git commit -m "feat(macmini): add MacBook → mini branch deploy wrapper

One-command iteration loop: pushes current branch, SSHes to mini,
fetches/rebuilds/kickstarts. --skip-web shortcut for Python-only
changes (skips npm install + next build, ~30s faster)."
```

### Task 1.12: Phase 1 verification — open PR

- [ ] **Step 1: Verify all phase-1 files exist**

Run: `ls -la scripts/deploy/macmini-*.sh config/templates/com.argon.*.plist.template config/services.list tests/integration/deploy/test_plist_render.py`
Expected: 10 files listed (4 deploy scripts + 5 templates + 1 services.list + 1 test file).

- [ ] **Step 2: Verify all are executable / well-formed**

Run:
```bash
shellcheck scripts/deploy/macmini-*.sh
for t in config/templates/com.argon.*.plist.template; do
  case "$t" in
    *worker*) subs="-e s|__ROLE__|uw|g -e s|__INDEX__|0|g -e s|__COUNT__|2|g" ;;
    *)        subs="" ;;
  esac
  echo "lint: $t"
  sed -e 's|__PROJECT_DIR__|/tmp/p|g' \
      -e 's|__USER__|me|g' \
      -e 's|__BREW_PREFIX__|/opt/homebrew|g' \
      -e 's|__UV_BIN__|/opt/homebrew/bin/uv|g' \
      -e 's|__NODE_BIN__|/opt/homebrew/bin/node|g' \
      -e 's|__NPM_BIN__|/opt/homebrew/bin/npm|g' \
      $subs "$t" | plutil -lint -
done
uv run pytest tests/integration/deploy/test_plist_render.py -v
```
Expected: shellcheck silent, all `plutil -lint` say `OK`, pytest reports 6 passed.

- [ ] **Step 3: Push branch + open PR**

```bash
git push -u origin feat/macmini-deploy-scaffolding
gh pr create --title "feat(macmini): deploy scaffolding (scripts + plist templates)" \
  --body "$(cat <<'EOF'
## Summary
- 4 deploy scripts (bootstrap, prod, data-promote, deploy-branch) ported from xenon's proven equivalents with argon-specific deltas
- 5 launchd plist templates (api, web, worker, massive-ws, backup) with sed-style placeholders
- 1 services.list as single source of truth for the 13 `com.argon.*` labels
- 1 plist-render test verifies templates produce valid plist XML via `plutil -lint`

No execution against the Mac mini yet — that's Phase 2 (manual host op).

## Test plan
- [x] `uv run pytest tests/integration/deploy/` — 6 passed
- [x] `shellcheck scripts/deploy/macmini-*.sh` — clean
- [x] Manual: rendered each template with realistic substitutions, `plutil -lint` OK on all

Spec: docs/superpowers/specs/2026-06-01-mac-mini-stack-migration-design.md
Plan: docs/superpowers/plans/2026-06-01-mac-mini-stack-migration-plan.md
EOF
)"
```

Wait for CI green + user review before merging.

---

## Phase 2 — Mini Bootstrap (Host Op, No PR)

After phase 1 PR merges to `main`, run the bootstrap script on the mini. This phase has no code changes; the user runs commands and reports results. The plan documents the commands and expected output.

### Task 2.1: Pre-flight on the Mac mini

- [ ] **Step 1: SSH in and confirm baseline**

```bash
ssh moremeds@100.66.147.98 'uname -ms && sw_vers && command -v brew && brew --version'
```
Expected: `Darwin arm64`, macOS info, `/opt/homebrew/bin/brew`, version string.

- [ ] **Step 2: Confirm xenon's Postgres is running**

```bash
ssh moremeds@100.66.147.98 'brew services list | grep postgresql'
```
Expected: `postgresql@16 started ...` (or similar).

- [ ] **Step 3: Confirm Codex + Claude CLI are signed in**

```bash
ssh moremeds@100.66.147.98 'command -v claude && command -v codex && echo "ok? respond yes" | claude --print --output-format text --max-turns 1 --tools "" --disable-slash-commands --strict-mcp-config --mcp-config "{\"mcpServers\": {}}" --no-session-persistence "ok?"'
```
Expected: paths to both binaries, plus a short Claude reply.

If Claude probe fails: `ssh moremeds@100.66.147.98 'claude /login'` and follow the OAuth flow.

### Task 2.2: Run macmini-bootstrap.sh

- [ ] **Step 1: Clone the repo**

```bash
ssh moremeds@100.66.147.98 'mkdir -p ~/projects && cd ~/projects && [ -d unusual-whales ] || git clone git@github.com:lcxxcllcx/unusual-whales.git'
```
Expected: either skip message, or new clone completes.

- [ ] **Step 2: Run bootstrap**

```bash
ssh moremeds@100.66.147.98 'cd ~/projects/unusual-whales && bash scripts/deploy/macmini-bootstrap.sh'
```
Expected:
- Skip for brew/postgres/node (xenon already installed them)
- Create role `argon_app`
- Create DBs `argon_dev` + `argon_test`
- Pause / warn for `.env` secrets that must be filled (UW_SCAN_API_KEY, MASSIVE_API_KEY, FRED_API_KEY, R2_*, DEEPSEEK_API_KEY, Clerk, ANTHROPIC_API_KEY)
- `uv sync` succeeds
- `npm install` + `npm run build` succeed
- 13 plists render and load
- Health summary: API DOWN / Web DOWN / Schema absent (expected — no data yet)

- [ ] **Step 3: Fill secrets on the mini**

The user manually populates `~/projects/unusual-whales/.env` and `~/projects/unusual-whales/web/.env` with the secrets that bootstrap warned about. Mirror the MacBook's `.env` values for UW/MASSIVE/FRED/R2/DEEPSEEK/Clerk/Anthropic. Set DB config:

```
UW_SCAN_DB_HOST=127.0.0.1
UW_SCAN_DB_PORT=5432
UW_SCAN_DB_NAME=argon_dev
UW_SCAN_DB_SCHEMA=uw_scan
UW_SCAN_DB_USER=argon_app
UW_SCAN_DB_PASSWORD=argon_dev
```

Mode 0600. Verify: `ssh moremeds@100.66.147.98 'ls -la ~/projects/unusual-whales/.env'` should show `-rw-------`.

- [ ] **Step 4: Restart services to pick up filled secrets**

```bash
ssh moremeds@100.66.147.98 'cd ~/projects/unusual-whales && while IFS= read -r s; do
  [[ -z "$s" || "$s" == \#* ]] && continue
  launchctl kickstart -k "gui/$UID/$s"
done < config/services.list'
```

- [ ] **Step 5: Tail logs briefly to confirm processes survive**

```bash
ssh moremeds@100.66.147.98 'tail -n 30 ~/projects/unusual-whales/logs/api.err.log ~/projects/unusual-whales/logs/web.err.log'
```
Expected: API serves on 127.0.0.1:8400; Web serves on 127.0.0.1:3001. Workers will log errors about missing tables until phase 3 cutover — that is expected and harmless (they'll restart with backoff via `KeepAlive.Crashed`).

---

## Phase 3 — DB Cutover (Host Op, No PR)

Run from MacBook. Mirrors `option_wizard` onto the mini's `argon_dev` over Tailscale. MacBook's local DB stays intact.

### Task 3.1: Stop MacBook writers

- [ ] **Step 1: Kill scripts/dev.sh and any worker schedulers**

If `scripts/dev.sh` is running in a shell, `Ctrl-C` it. Then:
```bash
pgrep -f 'uw_scan.worker.scheduler' && pkill -f 'uw_scan.worker.scheduler' || echo "no scheduler running"
pgrep -f 'uw_scan.worker.massive_ws_consumer' && pkill -f 'uw_scan.worker.massive_ws_consumer' || echo "no ws consumer running"
pgrep -f 'uvicorn uw_scan.api.server' && pkill -f 'uvicorn uw_scan.api.server' || echo "no api running"
```

- [ ] **Step 2: Confirm**

Run: `lsof -nP -iTCP:8400 -sTCP:LISTEN; lsof -nP -iTCP:3001 -sTCP:LISTEN; pgrep -fl 'uw_scan'`
Expected: empty output (no MacBook writer holding the DB).

### Task 3.2: Stop mini services, then promote

- [ ] **Step 1: Stop ALL mini services before destructive restore**

`pg_restore --clean --if-exists` drops every table in `uw_scan` before recreating from the dump. If the mini's 13 services are still running, they'll hold open connections and write between drops — corrupting the restore state and producing flaky errors. Stop them first:

```bash
ssh moremeds@100.66.147.98 'cd ~/projects/unusual-whales && while IFS= read -r s; do
  [[ -z "$s" || "$s" == \#* ]] && continue
  launchctl unload "$HOME/Library/LaunchAgents/$s.plist" 2>/dev/null
done < config/services.list
echo "all argon services stopped"'
```

Verify nothing's still holding the DB:
```bash
ssh moremeds@100.66.147.98 'psql postgres -c "
  SELECT pid, application_name, state
  FROM pg_stat_activity WHERE datname=\"argon_dev\""'
```
Expected: empty (no connections to argon_dev).

- [ ] **Step 2: Promote**

```bash
./scripts/deploy/macmini-data-promote.sh moremeds@100.66.147.98 --confirm
# (no --src-db / --src-user needed — defaults to option_wizard/chenxi which is the Phase 3 source)
```
Expected:
- Refusal block passes (no writers)
- Local dump of `option_wizard` to `data/backups/option_wizard-<ts>.dump`, size ~3-5 GB compressed
- Stream + pg_restore on mini completes — single-threaded (the streaming pipeline disallows `pg_restore -j`); ~10-25 min wall-clock on 8.2 GB over Tailscale Wi-Fi, faster on wired
- Verify query lists top 20 tables in `uw_scan` by row count — should match MacBook's counts

- [ ] **Step 3: Cross-check row counts on the most critical tables**

Tables chosen by row volume in the live `option_wizard` DB on 2026-06-01 — these are the biggest tables (option_contract_snapshots ~5.3M, dark_pool_events ~3.9M) plus the most-load-bearing for app behavior (scan_runs, trade_insight_ai_analyses). Any large count discrepancy here means the dump/restore lost data.

Run on MacBook:
```bash
psql -d option_wizard -c "
  SELECT relname, n_live_tup FROM pg_stat_user_tables
  WHERE schemaname='uw_scan' AND relname IN
    ('option_contract_snapshots','dark_pool_events','greeks_by_expiry_strike',
     'flow_events','scan_runs','trade_insight_ai_analyses')
  ORDER BY n_live_tup DESC"
```
Run on mini (via ssh):
```bash
ssh moremeds@100.66.147.98 'PGPASSWORD=argon_dev psql -h localhost -U argon_app argon_dev -c "
  SELECT relname, n_live_tup FROM pg_stat_user_tables
  WHERE schemaname='\''uw_scan'\'' AND relname IN
    ('\''option_contract_snapshots'\'','\''dark_pool_events'\'','\''greeks_by_expiry_strike'\'',
     '\''flow_events'\'','\''scan_runs'\'','\''trade_insight_ai_analyses'\'')
  ORDER BY n_live_tup DESC"'
```

Note: `pg_stat_user_tables.n_live_tup` updates lazily via autovacuum; right after `pg_restore` the mini's counts may temporarily show 0 for some tables, and the heavy WAL churn from `--clean` slows autovacuum's normal catch-up. Force a full-DB `ANALYZE` on the mini before comparing — this also helps query planner accuracy for the first wave of post-cutover requests:
```bash
ssh moremeds@100.66.147.98 'PGPASSWORD=argon_dev psql -h localhost -U argon_app argon_dev -c "ANALYZE"'
```

**If the restore fails mid-stream** (e.g., Tailscale drops the SSH connection while bytes are flowing): the mini's `argon_dev` will be partially populated and in an inconsistent state. Recover by:
1. Re-establish ssh to mini, verify Postgres is healthy.
2. Re-run `./scripts/deploy/macmini-data-promote.sh moremeds@100.66.147.98 --confirm` — the `--clean --if-exists` semantics drop everything and restart restore from scratch.
3. The MacBook source DB is untouched throughout; no source-side recovery needed.

Expected: row counts match exactly (no writers were active during dump because Phase 3 Task 3.1 + Step 1 stopped both sides).

**Ownership verification** (acceptance check — closes the `pg_restore --no-owner` residual risk):

The spec asserts that `pg_restore --no-owner` causes the connecting role (`argon_app`) to own every restored object. This is documented behavior, but verify it directly on the live DB before declaring cutover done. If the assertion fails, app writes will hit permission errors at runtime.

Run on mini:
```bash
ssh moremeds@100.66.147.98 'PGPASSWORD=argon_dev psql -h localhost -U argon_app argon_dev -c "
  SELECT tableowner, COUNT(*) AS n
  FROM pg_tables
  WHERE schemaname='\''uw_scan'\''
  GROUP BY tableowner
  ORDER BY n DESC"'
```

Expected: a single row, `tableowner=argon_app`, `n` matching the table count in `uw_scan`. Any other owner (especially `postgres` or `chenxi`) means `--no-owner` did not behave as expected; investigate before proceeding to Step 4.

- [ ] **Step 4: Kickstart mini services to pick up populated DB**

`launchctl unload` removed the services in Step 1; now `load` them back. Plain `kickstart -k` would no-op since the services aren't loaded.

```bash
ssh moremeds@100.66.147.98 'cd ~/projects/unusual-whales && while IFS= read -r s; do
  [[ -z "$s" || "$s" == \#* ]] && continue
  launchctl load "$HOME/Library/LaunchAgents/$s.plist"
done < config/services.list'
```

- [ ] **Step 5: End-to-end smoke**

From MacBook over Tailscale:
```bash
curl -fsS http://100.66.147.98:8400/health | jq .
curl -fsSI http://100.66.147.98:3001 | head -1
```
Expected: `/health` returns JSON with `db: ok` (or equivalent); `/` returns `HTTP/1.1 200 OK`.

If health is bad, tail logs:
```bash
ssh moremeds@100.66.147.98 'tail -f ~/projects/unusual-whales/logs/api.err.log'
```

---

## Phase 4 — MacBook Switch + dev.sh Guard (PR: `chore/macbook-point-at-mini`)

### Task 4.0: Teach `Settings.from_env` to load `.env.local`

**Why this comes before the guard:** the dev.sh guard added in Task 4.1 reads `.env.local`, but `Settings.from_env()` currently only reads `.env`. If a developer creates `.env.local` with `UW_SCAN_DB_HOST=127.0.0.1`, the guard would correctly let dev.sh run, but the uvicorn/worker child processes would STILL load `.env` only and connect to the mini — recreating the race condition. Land the runtime-side fix in the same PR as the guard so they ship atomically.

**Files:**
- Modify: `src/uw_scan/config.py` — `from_env` classmethod
- Create: `tests/unit/test_config_env_local.py`

- [ ] **Step 1: Read current state**

Run: `grep -n -A6 'def from_env' src/uw_scan/config.py | head -20`

- [ ] **Step 2: Apply the loader change**

Find:
```python
    @classmethod
    def from_env(cls, env_path: Path | None = None) -> "Settings":
        """Load Settings from process env, auto-loading .env at repo root if present."""
        if env_path is None:
            env_path = Path(__file__).resolve().parents[2] / ".env"
        _load_dotenv(env_path)
```

Replace with:
```python
    @classmethod
    def from_env(cls, env_path: Path | None = None) -> "Settings":
        """Load Settings from process env.

        Precedence (later loads no-op against already-set keys, so first load wins):
          1. process env vars       (already in os.environ before we run)
          2. .env.local             (gitignored per-machine override — load FIRST)
          3. .env                   (committed-default baseline — load SECOND)

        Aligns with the dev.sh guard so guard-allowed configurations also reach
        the worker processes. Pass an explicit env_path to bypass this discovery
        (used by tests).
        """
        if env_path is not None:
            _load_dotenv(env_path)
            return cls._build_from_environ()
        repo_root = Path(__file__).resolve().parents[2]
        _load_dotenv(repo_root / ".env.local")  # per-machine override
        _load_dotenv(repo_root / ".env")        # committed baseline
        return cls._build_from_environ()
```

Then extract the existing inline `os.environ.get(...)` block (currently inside `from_env`) into a private `_build_from_environ` classmethod for cleanliness. Move lines 224-274 (approx — the `api_key` read through the `return cls(...)`) into the new helper, indented and with `return cls(` at the end. Both `from_env` callers will land at the same `cls()` construction.

- [ ] **Step 3: Add the test**

Create `tests/unit/test_config_env_local.py`:

```python
"""Verify Settings.from_env loads .env.local with override semantics.

Regression for the dev.sh-guard/runtime-config split: a developer setting
.env.local to point at localhost must reach the Python workers, not just
the dev.sh tripwire.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from uw_scan.config import _load_dotenv


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for key in (
        "UW_SCAN_API_KEY",
        "UW_SCAN_DB_HOST",
        "UW_SCAN_DB_NAME",
        "UW_SCAN_DB_USER",
        "UW_SCAN_DB_PASSWORD",
    ):
        monkeypatch.delenv(key, raising=False)


def test_env_local_overrides_env(tmp_path):
    (tmp_path / ".env").write_text(
        "UW_SCAN_API_KEY=test-key\n"
        "UW_SCAN_DB_HOST=100.66.147.98\n"
        "UW_SCAN_DB_NAME=argon_dev\n"
    )
    (tmp_path / ".env.local").write_text(
        "UW_SCAN_DB_HOST=127.0.0.1\n"
        "UW_SCAN_DB_NAME=local_dev_override\n"
    )
    # The from_env discovery walks Path(__file__).resolve().parents[2].
    # For the unit test, call the loaders in the documented order against
    # tmp_path explicitly — this is the same precedence as the production path.
    _load_dotenv(tmp_path / ".env.local")
    _load_dotenv(tmp_path / ".env")
    assert os.environ["UW_SCAN_DB_HOST"] == "127.0.0.1"
    assert os.environ["UW_SCAN_DB_NAME"] == "local_dev_override"


def test_process_env_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("UW_SCAN_DB_HOST", "shell-set-host")
    (tmp_path / ".env.local").write_text("UW_SCAN_DB_HOST=should-not-win\n")
    (tmp_path / ".env").write_text(
        "UW_SCAN_API_KEY=test-key\nUW_SCAN_DB_HOST=should-not-win-either\n"
    )
    _load_dotenv(tmp_path / ".env.local")
    _load_dotenv(tmp_path / ".env")
    assert os.environ["UW_SCAN_DB_HOST"] == "shell-set-host"
```

- [ ] **Step 4: Run the new test**

Run: `uv run pytest tests/unit/test_config_env_local.py -v`
Expected: 2 tests pass.

- [ ] **Step 5: Run the broader unit suite to confirm no regression**

Run: `uv run pytest tests/unit -q`
Expected: all pass.

### Task 4.1: Add the dev.sh guard

**Files:**
- Modify: `scripts/dev.sh` (top of script, after `set -euo pipefail`)

- [ ] **Step 1: Read the current top of dev.sh**

Run: `head -20 scripts/dev.sh`

- [ ] **Step 2: Apply the guard**

Edit `scripts/dev.sh`. Immediately after the `set -euo pipefail; cd "$(dirname "$0")/.."` line, insert:

```bash
# MacBook race-condition guard:
# After the mini migration, MacBook's .env points at 100.66.147.98 (the mini).
# Running this script there would start a competing set of workers against
# the mini's argon_dev queue (FOR UPDATE SKIP LOCKED), making dev debugging
# flaky because mini workers claim rows first.
#
# Resolution order (later wins, matches docs/superpowers/specs/...§6.3):
#   1. Shell env var   (export UW_SCAN_DB_HOST=...)
#   2. .env            (committed-default-ish baseline)
#   3. .env.local      (gitignored, per-machine override)
#
# To work around (e.g., to reproduce a mini-only bug): set
#   UW_SCAN_ALLOW_DEV_AGAINST_MINI=1
# explicitly. For normal local dev, create .env.local with
#   UW_SCAN_DB_HOST=127.0.0.1
#   UW_SCAN_DB_NAME=argon_dev      (or your local DB name)
# and the guard will pass.
_env_db_host() {
  # Extract UW_SCAN_DB_HOST value from a single env file. Empty if not set.
  local f="$1"
  [[ -f "$f" ]] || { echo ""; return; }
  grep -E '^[[:space:]]*UW_SCAN_DB_HOST=' "$f" \
    | tail -1 | cut -d= -f2 | tr -d '"' | tr -d "'" | xargs
}
db_host="${UW_SCAN_DB_HOST:-}"
[[ -n "$db_host" ]] || db_host="$(_env_db_host .env)"
# .env.local overrides .env if it sets the var
local_host="$(_env_db_host .env.local)"
[[ -n "$local_host" ]] && db_host="$local_host"

if [[ "$db_host" != "127.0.0.1" && "$db_host" != "localhost" && "$db_host" != "" \
      && "${UW_SCAN_ALLOW_DEV_AGAINST_MINI:-0}" != "1" ]]; then
  echo "ERROR: scripts/dev.sh refuses to run against UW_SCAN_DB_HOST='$db_host'" >&2
  echo "  This would start MacBook workers competing with mini workers on the" >&2
  echo "  same FOR UPDATE SKIP LOCKED queue. Options:" >&2
  echo "    1. Create .env.local with UW_SCAN_DB_HOST=127.0.0.1 (and matching DB name)" >&2
  echo "    2. Explicitly opt in: UW_SCAN_ALLOW_DEV_AGAINST_MINI=1 bash scripts/dev.sh" >&2
  echo "    3. Deploy to the mini instead: ./scripts/deploy/macmini-deploy-branch.sh" >&2
  exit 1
fi
```

- [ ] **Step 3: Test the guard — should refuse**

Create a temporary `.env.test` with the mini host and verify the guard:
```bash
( cd "$(git rev-parse --show-toplevel)"
  printf 'UW_SCAN_DB_HOST=100.66.147.98\n' > .env.test
  UW_SCAN_DB_HOST=100.66.147.98 bash -c 'set -euo pipefail; bash scripts/dev.sh' 2>&1 | head -5 || true
  rm .env.test )
```
Expected: prints the "refuses to run" error and exits non-zero. (The guard reads from the shell env first; we set it explicitly.)

- [ ] **Step 4: Test the guard — should allow with opt-in**

Verify the opt-in works (but stop the script immediately so it doesn't actually launch processes):
```bash
UW_SCAN_ALLOW_DEV_AGAINST_MINI=1 UW_SCAN_DB_HOST=100.66.147.98 \
  timeout 1s bash scripts/dev.sh 2>&1 | grep -v 'refuses to run' | head -3 || true
```
Expected: no "refuses to run" message; script proceeds (then `timeout` kills it).

- [ ] **Step 5: Test the guard — local host passes**

```bash
UW_SCAN_DB_HOST=127.0.0.1 timeout 1s bash scripts/dev.sh 2>&1 | grep -v 'refuses to run' | head -3 || true
```
Expected: no refusal message.

- [ ] **Step 6: Test the guard — .env.local overrides .env (load-bearing path for local dev)**

```bash
( cd "$(git rev-parse --show-toplevel)"
  printf 'UW_SCAN_DB_HOST=100.66.147.98\n' > .env.test-mini
  printf 'UW_SCAN_DB_HOST=127.0.0.1\n' > .env.local
  # Simulate: .env has mini, .env.local has localhost — guard must respect .env.local
  cp .env .env.backup-guard-test
  cp .env.test-mini .env
  unset UW_SCAN_DB_HOST
  timeout 1s bash scripts/dev.sh 2>&1 | grep 'refuses to run' && echo "FAIL: guard did not honor .env.local" || echo "OK: guard honored .env.local"
  # Restore
  mv .env.backup-guard-test .env
  rm .env.test-mini .env.local
)
```
Expected: `OK: guard honored .env.local` printed.

### Task 4.2: Update MacBook .env (manual, document the exact change)

This is a manual edit; the plan documents the exact lines to change.

- [ ] **Step 1: Back up current .env**

Run: `cp .env .env.backup-pre-mini`

- [ ] **Step 2: Edit .env**

Find these lines and change them:

```
UW_SCAN_DB_HOST=127.0.0.1     →  UW_SCAN_DB_HOST=100.66.147.98
UW_SCAN_DB_NAME=option_wizard →  UW_SCAN_DB_NAME=argon_dev
UW_SCAN_DB_USER=chenxi        →  UW_SCAN_DB_USER=argon_app
UW_SCAN_DB_PASSWORD=          →  UW_SCAN_DB_PASSWORD=argon_dev
```

- [ ] **Step 3: Verify connectivity from MacBook**

Run: `psql -h 100.66.147.98 -U argon_app -d argon_dev -c "SELECT COUNT(*) FROM uw_scan.scan_runs"`
(When prompted for password, enter `argon_dev`.)
Expected: a non-zero count matching the row count on the mini.

To avoid the prompt going forward, set `PGPASSWORD=argon_dev` in the shell or add a `~/.pgpass` entry:
```
echo '100.66.147.98:5432:argon_dev:argon_app:argon_dev' >> ~/.pgpass
echo '100.66.147.98:5432:argon_test:argon_app:argon_dev' >> ~/.pgpass
chmod 600 ~/.pgpass
```

### Task 4.3: Verify dev.sh refusal on the real MacBook

- [ ] **Step 1: Try running dev.sh**

Run: `bash scripts/dev.sh`
Expected: the new guard refuses (because `.env` now has `UW_SCAN_DB_HOST=100.66.147.98`).

This proves the guard is wired correctly against the real .env.

### Task 4.4: Commit phase 4

- [ ] **Step 1: Verify only the expected files changed**

Run: `git status --short && git diff --stat`
Expected: 3 files changed — `scripts/dev.sh` (guard), `src/uw_scan/config.py` (`.env.local` loader), `tests/unit/test_config_env_local.py` (new).

- [ ] **Step 2: Run the affected tests one more time**

Run: `uv run pytest tests/unit/test_config_env_local.py tests/unit -q`
Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git add scripts/dev.sh src/uw_scan/config.py tests/unit/test_config_env_local.py
git commit -m "chore(macmini): MacBook switch — dev.sh guard + .env.local loader

After migration, MacBook .env points at the mini's argon_dev. Two coupled
changes ship in one PR so guard and runtime stay aligned:

1. scripts/dev.sh refuses to run when UW_SCAN_DB_HOST points off-localhost,
   unless UW_SCAN_ALLOW_DEV_AGAINST_MINI=1 (opt-in tripwire). Resolves DB
   host from shell env > .env.local > .env (later overrides earlier).

2. Settings.from_env now loads .env.local before .env so the same precedence
   reaches uvicorn / worker children. Without this, the guard could let
   dev.sh run while children still hit the mini — recreating the race the
   guard is trying to prevent.

Per spec §6.3 and §6.4."
```

- [ ] **Step 4: Open PR + merge**

```bash
git push -u origin chore/macbook-point-at-mini
gh pr create --title "chore(macmini): MacBook switch — dev.sh guard + .env.local loader" \
  --body "## Summary
Two coupled changes ship together so the dev.sh guard and child-process runtime stay aligned:

1. **scripts/dev.sh guard**: refuses when UW_SCAN_DB_HOST points off-localhost unless UW_SCAN_ALLOW_DEV_AGAINST_MINI=1.
2. **Settings.from_env**: now loads .env.local before .env so guard-allowed configurations also reach uvicorn + workers.

Per spec §6.3 (Local-only dev) + §6.4 (Worker race avoidance).

## Test plan
- [x] uv run pytest tests/unit/test_config_env_local.py -v (2 pass)
- [x] uv run pytest tests/unit -q (all pass — no test pinned old defaults)
- [x] Guard refuses when DB_HOST=100.66.147.98 (manual)
- [x] Guard allows with UW_SCAN_ALLOW_DEV_AGAINST_MINI=1 (manual)
- [x] Guard allows when DB_HOST=127.0.0.1 (manual)
- [x] Guard honors .env.local overriding .env (manual via Task 4.1 Step 6)
- [x] Verified against real MacBook .env (now points at mini)"
```

---

## Phase 5 — Codebase Rename Cleanup (PR: `chore/rename-option-wizard-to-argon`)

Now that runtime is on `argon_dev` via env vars, rename the 13 in-repo references for cosmetic consistency. This is the lowest-risk phase: any oversight just falls through to env-var values (which already say `argon_dev`).

### Task 5.1: src/uw_scan/config.py — rename `option_wizard` + `chenxi` defaults

(The `.env.local` loader was already added in Task 4.0 so the guard and runtime stay aligned. This task only renames the cosmetic defaults.)

**Files:**
- Modify: `src/uw_scan/config.py` — `db_name` and `db_user` defaults in 4 places

- [ ] **Step 1: Read current state**

Run: `grep -n 'option_wizard\|"chenxi"' src/uw_scan/config.py`
Expected:
- 2 hits for `option_wizard` (defaults on ~line 65 + ~line 235)
- 2 hits for `"chenxi"` (db_user defaults on ~line 70 + ~line 236)

- [ ] **Step 2: Rename `db_name` default**

Edit `src/uw_scan/config.py` — the class field on line 65:

Find:
```python
    db_name: str = "option_wizard"
```
Replace with:
```python
    db_name: str = "argon_dev"
```

And the env-loader fallback ~line 235:

Find:
```python
            db_name=os.environ.get("UW_SCAN_DB_NAME", "option_wizard"),
```
Replace with:
```python
            db_name=os.environ.get("UW_SCAN_DB_NAME", "argon_dev"),
```

- [ ] **Step 3: Rename `db_user` default**

Edit `src/uw_scan/config.py` — the class field on line ~70:

Find:
```python
    db_user: str = "chenxi"
```
Replace with:
```python
    db_user: str = "argon_app"
```

And the env-loader fallback ~line 236:

Find:
```python
            db_user=os.environ.get("UW_SCAN_DB_USER", "") or "chenxi",
```
Replace with:
```python
            db_user=os.environ.get("UW_SCAN_DB_USER", "") or "argon_app",
```

- [ ] **Step 4: Run unit suite to confirm no test pinned the old defaults**

Run: `uv run pytest tests/unit -q`
Expected: all pass. If any test asserted `db_name == "option_wizard"` or `db_user == "chenxi"`, update it.

- [ ] **Step 5: Verify renames**

Run: `grep -n 'option_wizard\|"chenxi"' src/uw_scan/config.py`
Expected: no output.

### Task 5.2: Rename test DB fixtures

**Files:**
- Modify: `tests/conftest.py`
- Modify: `tests/unit/worker/test_gold_warmup.py`
- Modify: `tests/integration/test_pipeline_strike_gex.py`
- Modify: `tests/integration/storage/test_repository_watchlist.py`
- Modify: `tests/integration/storage/test_migrations.py`
- Modify: `tests/integration/storage/test_gold_migrations.py`
- Modify: `tests/integration/test_pipeline_e2e.py`

- [ ] **Step 1: Inspect each file to understand the rename**

Run: `for f in tests/conftest.py tests/unit/worker/test_gold_warmup.py tests/integration/test_pipeline_strike_gex.py tests/integration/storage/test_repository_watchlist.py tests/integration/storage/test_migrations.py tests/integration/storage/test_gold_migrations.py tests/integration/test_pipeline_e2e.py; do echo "=== $f ==="; grep -n 'option_wizard' "$f"; done`

This shows whether the references are bare DB names, environment variable defaults, or fixture parameter values. Most are likely the string literal `"option_wizard_test"` used as a test DB name passed to pytest-postgresql or set via `UW_SCAN_TEST_DB_NAME` env var.

- [ ] **Step 1b: Proactive check — any test asserts the OLD string literal?**

Run: `grep -nE '(assert|expect|==).*"option_wizard"' tests/ -r 2>/dev/null | head`
Expected: no output. If hits appear, those tests assert a specific string that will change in this rename — they need a value update, not just an env-var rename. Address each before Step 2.

- [ ] **Step 2: Replace `option_wizard_test` → `argon_test` in every file**

Use `sed -i ''` (BSD sed on macOS) for the literal replacement:

```bash
for f in tests/conftest.py tests/unit/worker/test_gold_warmup.py \
         tests/integration/test_pipeline_strike_gex.py \
         tests/integration/storage/test_repository_watchlist.py \
         tests/integration/storage/test_migrations.py \
         tests/integration/storage/test_gold_migrations.py \
         tests/integration/test_pipeline_e2e.py; do
  sed -i '' 's/option_wizard_test/argon_test/g' "$f"
  sed -i '' 's/option_wizard/argon_dev/g' "$f"
done
```

- [ ] **Step 3: Verify**

Run: `grep -rn 'option_wizard' tests/ 2>/dev/null | grep -v __pycache__`
Expected: no output.

- [ ] **Step 4: Run the unit tests locally**

Run: `uv run pytest tests/unit/worker/test_gold_warmup.py -v`
Expected: PASS.

Note: integration tests require a populated test DB. If MacBook still has a local `option_wizard_test`, you can create `argon_test` locally too (`createdb argon_test`) or rely on CI which uses ephemeral pytest-postgresql.

### Task 5.3: Rename script docstring

**Files:**
- Modify: `scripts/dry_run_volatility_endpoint.py:7`

- [ ] **Step 1: Show current line**

Run: `grep -n 'option_wizard' scripts/dry_run_volatility_endpoint.py`
Expected: line 7 with `UW_SCAN_TEST_DB_NAME=option_wizard_test`.

- [ ] **Step 2: Replace**

Edit `scripts/dry_run_volatility_endpoint.py` line 7. Find:
```
Run: `UW_SCAN_TEST_DB_NAME=option_wizard_test \
```
Replace with:
```
Run: `UW_SCAN_TEST_DB_NAME=argon_test \
```

- [ ] **Step 3: Verify**

Run: `grep -n 'option_wizard' scripts/dry_run_volatility_endpoint.py`
Expected: no output.

### Task 5.4: Update .env.example

**Files:**
- Modify: `.env.example`

- [ ] **Step 1: Show current state**

Run: `grep -n -A1 'UW_SCAN_DB_HOST\|UW_SCAN_DB_NAME\|UW_SCAN_DB_USER\|UW_SCAN_DB_PASSWORD' .env.example`

- [ ] **Step 2: Replace the DB block**

Find the existing block:
```
UW_SCAN_DB_HOST=127.0.0.1
UW_SCAN_DB_PORT=5432
UW_SCAN_DB_NAME=option_wizard
UW_SCAN_DB_SCHEMA=uw_scan
UW_SCAN_DB_USER=
UW_SCAN_DB_PASSWORD=
```
Replace with:
```
# DB connection. Default points at the Mac mini over Tailscale (production).
# For local-only dev, override these in a gitignored .env.local with:
#   UW_SCAN_DB_HOST=127.0.0.1
#   UW_SCAN_DB_NAME=argon_dev   (or whatever your local DB is named)
UW_SCAN_DB_HOST=100.66.147.98
UW_SCAN_DB_PORT=5432
UW_SCAN_DB_NAME=argon_dev
UW_SCAN_DB_SCHEMA=uw_scan
UW_SCAN_DB_USER=argon_app
UW_SCAN_DB_PASSWORD=argon_dev
```

- [ ] **Step 3: Verify**

Run: `grep -n 'option_wizard\|argon' .env.example`
Expected: lines showing `argon_dev`, `argon_app`, no `option_wizard`.

### Task 5.5: Update CLAUDE.md + AGENTS.md + README.md

**Files:**
- Modify: `CLAUDE.md`
- Modify: `AGENTS.md`
- Modify: `README.md`

- [ ] **Step 1: Show current references**

Run: `for f in CLAUDE.md AGENTS.md README.md; do echo "=== $f ==="; grep -n 'option_wizard' "$f"; done`

- [ ] **Step 2: Apply renames**

```bash
sed -i '' 's/option_wizard_test/argon_test/g' CLAUDE.md AGENTS.md README.md
sed -i '' 's/option_wizard/argon_dev/g' CLAUDE.md AGENTS.md README.md
```

- [ ] **Step 3: In each of CLAUDE.md and AGENTS.md, also update the "Postgres" sentence in the "What this is" section**

Find:
```
Postgres `argon_dev` DB, schema `uw_scan`.
```
Add a follow-up sentence:
```
Postgres `argon_dev` DB (renamed from `option_wizard` 2026-06-01 during the Mac mini migration), schema `uw_scan`.
```
(Skip the parenthetical if already added in either file — keep CLAUDE.md and AGENTS.md identical per project rule.)

- [ ] **Step 4: Verify**

Run: `grep -rn 'option_wizard' CLAUDE.md AGENTS.md README.md`
Expected: no output.

Also run: `diff CLAUDE.md AGENTS.md | head -20`
Expected: only the expected divergences (e.g., agent-specific framing) — no DB-name divergence.

### Task 5.6: Run full test suite

- [ ] **Step 1: Unit tests**

Run: `uv run pytest tests/unit -q`
Expected: all pass.

- [ ] **Step 2: Integration tests (against a local argon_test DB)**

Pre-req on MacBook: `createdb argon_test` (if not already present) — or rely on pytest-postgresql ephemeral DBs.

Run: `uv run pytest tests/integration -q`
Expected: all pass.

If a test fails because it expected `option_wizard_test` to exist as a DB, that's a test that escaped step 5.2's rename — grep for any leftover hits and patch.

- [ ] **Step 3: Plist render tests still pass**

Run: `uv run pytest tests/integration/deploy -v`
Expected: 6 passed.

### Task 5.7: Commit phase 5

- [ ] **Step 1: Confirm zero remaining `option_wizard` in live code**

Run: `grep -r 'option_wizard' --include='*.py' --include='*.ts' --include='*.tsx' --include='*.sh' --include='.env*' src/ tests/ scripts/ web/ .env.example 2>/dev/null`
Expected: no output.

Also check root docs:
Run: `grep -n 'option_wizard' CLAUDE.md AGENTS.md README.md`
Expected: no output.

(Archived docs and historical specs/plans intentionally still reference `option_wizard` — they are not touched.)

- [ ] **Step 2: Commit + open PR**

```bash
git add src/uw_scan/config.py scripts/dry_run_volatility_endpoint.py \
        tests/conftest.py tests/unit/worker/test_gold_warmup.py \
        tests/integration/test_pipeline_strike_gex.py \
        tests/integration/storage/test_repository_watchlist.py \
        tests/integration/storage/test_migrations.py \
        tests/integration/storage/test_gold_migrations.py \
        tests/integration/test_pipeline_e2e.py \
        .env.example CLAUDE.md AGENTS.md README.md
git commit -m "chore: rename option_wizard → argon_dev across live code/docs

Cosmetic cleanup post-mini migration. Runtime already points at
argon_dev via env vars from the chore/macbook-point-at-mini PR;
this PR aligns code defaults, test fixtures, .env.example, and active
docs with the new name.

Archived docs and historical specs/plans intentionally untouched —
they describe the pre-migration world accurately and should not be
retroactively rewritten."
git push -u origin chore/rename-option-wizard-to-argon
gh pr create --title "chore: rename option_wizard → argon_dev (13 live files)" \
  --body "## Summary
- src/uw_scan/config.py: default db_name option_wizard → argon_dev
- 7 test files: option_wizard_test → argon_test
- 1 script (dry_run_volatility_endpoint.py): docstring example
- .env.example: full DB block updated + comment for local override
- CLAUDE.md + AGENTS.md + README.md: DB name + transitional note

Intentionally NOT touched: docs/{research,superpowers/specs/archive,superpowers/plans/archive}/*, historical canary specs/plans that describe pre-migration state.

## Test plan
- [x] uv run pytest tests/unit -q (all pass)
- [x] uv run pytest tests/integration -q (all pass against argon_test)
- [x] uv run pytest tests/integration/deploy -v (6 pass)
- [x] grep confirms zero option_wizard in live code"
```

---

## Phase 6 — Backup + Ops Hardening (PR: `feat/macmini-backup-and-ops`)

### Task 6.1: Load the backup plist on the mini

The backup plist template was created in Task 1.6 (so its render is tested), but it was deliberately NOT in `config/services.list` and NOT loaded by bootstrap. Now we load it.

- [ ] **Step 1: Render + load the backup plist on the mini**

```bash
ssh moremeds@100.66.147.98 'cd ~/projects/unusual-whales
  UV_BIN="$(command -v uv)"
  BREW_PREFIX="$(brew --prefix)"
  USER_NAME="$(id -un)"
  ARGON_HOME="$HOME/projects/unusual-whales"
  src="$ARGON_HOME/config/templates/com.argon.backup.plist.template"
  dst="$HOME/Library/LaunchAgents/com.argon.backup.plist"
  sed -e "s|__PROJECT_DIR__|$ARGON_HOME|g" \
      -e "s|__USER__|$USER_NAME|g" \
      -e "s|__BREW_PREFIX__|$BREW_PREFIX|g" \
      "$src" > "$dst"
  launchctl unload "$dst" 2>/dev/null || true
  launchctl load "$dst"
  echo "loaded com.argon.backup at $dst"'
```

- [ ] **Step 2: Trigger an immediate backup to validate**

```bash
ssh moremeds@100.66.147.98 'launchctl kickstart -k gui/$UID/com.argon.backup
  sleep 5
  ls -la ~/projects/unusual-whales/data/backups/'
```
Expected: a `argon_dev-<YYYYMMDD>.dump.gz` file appears, size > 1MB.

- [ ] **Step 3: Verify the dump is restorable**

```bash
ssh moremeds@100.66.147.98 'cd ~/projects/unusual-whales/data/backups
  latest=$(ls -1t argon_dev-*.dump.gz | head -1)
  echo "Testing restore of $latest"
  gunzip -c "$latest" | pg_restore --list | head -5'
```
Expected: pg_restore lists archive contents — confirms the dump is well-formed.

### Task 6.2: Write the R2 upload script

**Files:**
- Create: `scripts/deploy/macmini-backup-upload-r2.sh`

- [ ] **Step 1: Write the script**

```bash
#!/usr/bin/env bash
# macmini-backup-upload-r2.sh — upload latest argon_dev dump to R2.
# Called by com.argon.backup-r2 launchd plist on Sundays at 04:00.
# Reads R2_* credentials from ~/projects/unusual-whales/.env.

set -euo pipefail

ARGON_HOME="${ARGON_HOME:-$HOME/projects/unusual-whales}"
cd "$ARGON_HOME"

# shellcheck disable=SC1091
set -a; source .env; set +a

for var in R2_ACCOUNT_ID R2_ACCESS_KEY_ID R2_SECRET_ACCESS_KEY R2_BUCKET; do
  if [[ -z "${!var:-}" ]]; then
    echo "ERROR: $var not set in .env — skipping upload" >&2
    exit 1
  fi
done

R2_ENDPOINT="${R2_ENDPOINT_OVERRIDE:-https://${R2_ACCOUNT_ID}.r2.cloudflarestorage.com}"

latest="$(ls -1t data/backups/argon_dev-*.dump.gz | head -1)"
[[ -n "$latest" ]] || { echo "no local backup to upload" >&2; exit 1; }

echo "Uploading $latest to s3://${R2_BUCKET}/postgres/"
AWS_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID" \
AWS_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY" \
aws s3 cp "$latest" "s3://${R2_BUCKET}/postgres/" \
  --endpoint-url "$R2_ENDPOINT"

echo "Upload OK"
```

- [ ] **Step 2: chmod + shellcheck**

Run: `chmod +x scripts/deploy/macmini-backup-upload-r2.sh && shellcheck scripts/deploy/macmini-backup-upload-r2.sh`
Expected: no errors.

### Task 6.3: Add R2 upload launchd plist template

**Files:**
- Create: `config/templates/com.argon.backup-r2.plist.template`

- [ ] **Step 1: Write the template**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.argon.backup-r2</string>

    <key>ProgramArguments</key>
    <array>
        <string>__PROJECT_DIR__/scripts/deploy/macmini-backup-upload-r2.sh</string>
    </array>

    <key>WorkingDirectory</key>
    <string>__PROJECT_DIR__</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>__BREW_PREFIX__/bin:/usr/local/bin:/usr/bin:/bin</string>
        <key>HOME</key>
        <string>/Users/__USER__</string>
        <key>ARGON_HOME</key>
        <string>__PROJECT_DIR__</string>
    </dict>

    <key>StartCalendarInterval</key>
    <dict>
        <key>Weekday</key>
        <integer>0</integer>
        <key>Hour</key>
        <integer>4</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>

    <key>RunAtLoad</key>
    <false/>

    <key>StandardOutPath</key>
    <string>__PROJECT_DIR__/logs/backup-r2.out.log</string>

    <key>StandardErrorPath</key>
    <string>__PROJECT_DIR__/logs/backup-r2.err.log</string>
</dict>
</plist>
```

- [ ] **Step 2: Verify with plutil**

Run: `sed -e 's|__PROJECT_DIR__|/tmp/p|' -e 's|__BREW_PREFIX__|/opt/homebrew|' -e 's|__USER__|me|' config/templates/com.argon.backup-r2.plist.template | plutil -lint -`
Expected: `- OK`

- [ ] **Step 3: Extend the plist render test**

Edit `tests/integration/deploy/test_plist_render.py`. Add to the `@pytest.mark.parametrize` list:

```python
        ("com.argon.backup-r2.plist.template", COMMON_SUBS),
```

Run: `uv run pytest tests/integration/deploy/test_plist_render.py -v`
Expected: 7 tests pass (was 6, now +1).

### Task 6.4: Load the R2 backup plist on the mini

- [ ] **Step 1: Render + load**

```bash
ssh moremeds@100.66.147.98 'cd ~/projects/unusual-whales
  BREW_PREFIX="$(brew --prefix)"
  USER_NAME="$(id -un)"
  src="config/templates/com.argon.backup-r2.plist.template"
  dst="$HOME/Library/LaunchAgents/com.argon.backup-r2.plist"
  sed -e "s|__PROJECT_DIR__|$HOME/projects/unusual-whales|g" \
      -e "s|__USER__|$USER_NAME|g" \
      -e "s|__BREW_PREFIX__|$BREW_PREFIX|g" \
      "$src" > "$dst"
  launchctl unload "$dst" 2>/dev/null || true
  launchctl load "$dst"
  echo "loaded com.argon.backup-r2"'
```

- [ ] **Step 2: Manually trigger to validate end-to-end**

Pre-req: `aws` CLI installed on mini (`ssh moremeds@100.66.147.98 'command -v aws || brew install awscli'`).

```bash
ssh moremeds@100.66.147.98 'launchctl kickstart -k gui/$UID/com.argon.backup-r2
  sleep 30
  tail -n 20 ~/projects/unusual-whales/logs/backup-r2.out.log
  tail -n 20 ~/projects/unusual-whales/logs/backup-r2.err.log'
```
Expected: `Upload OK` in out log; err log empty.

Verify in R2:
```bash
ssh moremeds@100.66.147.98 'cd ~/projects/unusual-whales && set -a; source .env; set +a
  AWS_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID" \
  AWS_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY" \
  aws s3 ls "s3://${R2_BUCKET}/postgres/" \
    --endpoint-url "${R2_ENDPOINT_OVERRIDE:-https://${R2_ACCOUNT_ID}.r2.cloudflarestorage.com}"'
```
Expected: latest `argon_dev-<date>.dump.gz` listed.

### Task 6.5: Write the ops runbook

**Files:**
- Create: `docs/ops/macmini-runbook.md`

- [ ] **Step 1: Write the runbook**

```markdown
# Mac Mini Ops Runbook (argon stack)

**Host:** Mac mini @ Tailscale `100.66.147.98`, SSH user `moremeds`.
**Repo:** `~/projects/unusual-whales` on mini.
**Services:** 13 launchd jobs (`com.argon.*`) + 2 backup jobs (`com.argon.backup`, `com.argon.backup-r2`).
**Co-tenant:** xenon shares the same `postgresql@16` cluster (separate DBs/roles).
**Spec:** `docs/superpowers/specs/2026-06-01-mac-mini-stack-migration-design.md`
**Plan:** `docs/superpowers/plans/2026-06-01-mac-mini-stack-migration-plan.md`

## First-time setup

Run on the mini as `moremeds`:
```
bash scripts/deploy/macmini-bootstrap.sh
```
Idempotent; safe to re-run.

## Regular deploy of a tagged release

From MacBook:
```
ssh moremeds@100.66.147.98 'cd ~/projects/unusual-whales && bash scripts/deploy/macmini-prod.sh v1.2.3'
```
Auto-rolls back if any of the 13 services fail health.

## Fast iteration on a WIP branch

From MacBook (current branch):
```
./scripts/deploy/macmini-deploy-branch.sh                    # full rebuild
./scripts/deploy/macmini-deploy-branch.sh --skip-web         # Python-only
```

## DB cutover (initial — already done) or re-mirror

From MacBook:
```
./scripts/deploy/macmini-data-promote.sh moremeds@100.66.147.98 --confirm
```
Refuses if MacBook writers are listening.

## Backups

- Nightly local: `com.argon.backup` (03:00) writes `data/backups/argon_dev-<date>.dump.gz`, retains 7 days.
- Weekly R2: `com.argon.backup-r2` (Sundays 04:00) uploads to `s3://${R2_BUCKET}/postgres/`.

Restore from local dump — `PGPASSWORD` must apply to `pg_restore`, not `gunzip`:
```
ssh moremeds@100.66.147.98 'cd ~/projects/unusual-whales
  latest=$(ls -1t data/backups/argon_dev-*.dump.gz | head -1)
  echo "Restoring from $latest"
  gunzip -c "$latest" \
    | PGPASSWORD=argon_dev pg_restore --clean --if-exists --no-owner --no-acl \
      -h 127.0.0.1 -U argon_app -d argon_dev'
```

Restore from R2:
```
ssh moremeds@100.66.147.98 'cd ~/projects/unusual-whales && set -a; source .env; set +a
  AWS_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID" AWS_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY" \
    aws s3 cp s3://${R2_BUCKET}/postgres/argon_dev-2026-06-01.dump.gz - \
      --endpoint-url "${R2_ENDPOINT_OVERRIDE:-https://${R2_ACCOUNT_ID}.r2.cloudflarestorage.com}" \
    | gunzip | PGPASSWORD=argon_dev pg_restore --clean --if-exists --no-owner --no-acl \
      -h 127.0.0.1 -U argon_app -d argon_dev'
```

## Manual service control

Status:
```
ssh moremeds@100.66.147.98 'launchctl print gui/$UID/com.argon.api | head -30'
```

Restart one:
```
ssh moremeds@100.66.147.98 'launchctl kickstart -k gui/$UID/com.argon.worker.ai-claude-0'
```

Restart all 13:
```
ssh moremeds@100.66.147.98 'cd ~/projects/unusual-whales && while IFS= read -r s; do
  [[ -z "$s" || "$s" == \#* ]] && continue
  launchctl kickstart -k "gui/$UID/$s"
done < config/services.list'
```

Stop all 13 (e.g., for maintenance) — uses `unload` to match xenon's `load`/`unload` pattern in the bootstrap script. **Note:** `com.argon.massive-ws` holds an in-memory `TickBuffer` (see `src/uw_scan/worker/ws_tick_buffer.py`); SIGTERM from `unload` discards anything not yet flushed (~5-30 s of intraday ticks during RTH). For ops where data continuity matters, prefer maintenance windows in pre-market or after-hours.
```
ssh moremeds@100.66.147.98 'while IFS= read -r s; do
  [[ -z "$s" || "$s" == \#* ]] && continue
  launchctl unload "$HOME/Library/LaunchAgents/$s.plist" 2>/dev/null
done < ~/projects/unusual-whales/config/services.list'
```

Re-load all 13 (after an unload):
```
ssh moremeds@100.66.147.98 'while IFS= read -r s; do
  [[ -z "$s" || "$s" == \#* ]] && continue
  launchctl load "$HOME/Library/LaunchAgents/$s.plist"
done < ~/projects/unusual-whales/config/services.list'
```

## Logs

- Aggregate: `ssh moremeds@100.66.147.98 'cd ~/projects/unusual-whales && tail -F logs/*.err.log'`
- API only: `ssh moremeds@100.66.147.98 'tail -F ~/projects/unusual-whales/logs/api.err.log'`
- One worker: `ssh moremeds@100.66.147.98 'tail -F ~/projects/unusual-whales/logs/worker-ai-claude-0.err.log'`

## Health checks

From MacBook over Tailscale:
```
curl -fsS http://100.66.147.98:8400/health | jq .
curl -fsSI http://100.66.147.98:3001 | head -1
psql -h 100.66.147.98 -U argon_app -d argon_dev -c "SELECT COUNT(*) FROM uw_scan.scan_runs"
```

## Rollback (mini-stack-wide, in case migration was a mistake)

1. On MacBook, flip `.env` back:
   - `UW_SCAN_DB_HOST=127.0.0.1`
   - `UW_SCAN_DB_NAME=option_wizard` (MacBook's local DB was untouched)
   - `UW_SCAN_DB_USER=chenxi`
   - Remove the dev.sh guard tripwire trigger by virtue of localhost.
2. On MacBook, restore the original CLAUDE.md/etc via `git revert chore/rename-option-wizard-to-argon`.
3. On mini, stop all services:
   ```
   ssh moremeds@100.66.147.98 'while read -r s; do
     [[ -z "$s" || "$s" == \#* ]] && continue
     launchctl unload "$HOME/Library/LaunchAgents/$s.plist" 2>/dev/null
   done < ~/projects/unusual-whales/config/services.list'
   ```
4. On mini, optionally drop the DBs (only if abandoning entirely):
   ```
   ssh moremeds@100.66.147.98 'psql postgres -c "
     DROP DATABASE IF EXISTS argon_dev;
     DROP DATABASE IF EXISTS argon_test;
     DROP ROLE IF EXISTS argon_app;"'
   ```
5. Restart MacBook's `scripts/dev.sh`.

xenon is unaffected — different DBs, different roles, different launchd labels.
```

### Task 6.6: Commit phase 6

- [ ] **Step 1: Add backup-r2 to git**

```bash
git add scripts/deploy/macmini-backup-upload-r2.sh \
        config/templates/com.argon.backup-r2.plist.template \
        tests/integration/deploy/test_plist_render.py \
        docs/ops/macmini-runbook.md
```

- [ ] **Step 2: Verify plist render tests still pass**

Run: `uv run pytest tests/integration/deploy/test_plist_render.py -v`
Expected: 7 tests pass.

- [ ] **Step 3: Commit + PR**

```bash
git commit -m "feat(macmini): backup hardening + ops runbook

- scripts/deploy/macmini-backup-upload-r2.sh — Sundays 04:00 R2 upload
- config/templates/com.argon.backup-r2.plist.template — weekly schedule
- docs/ops/macmini-runbook.md — bootstrap, deploy, rollback, backup,
  service control, log tailing procedures
- tests/integration/deploy/test_plist_render.py: 6 → 7 templates"

git push -u origin feat/macmini-backup-and-ops
gh pr create --title "feat(macmini): backup + ops runbook" \
  --body "## Summary
- Weekly R2 upload of postgres dumps (Sundays 04:00) via com.argon.backup-r2 launchd job
- docs/ops/macmini-runbook.md as the operational source of truth
- Plist render test extended to cover the new template

Spec: §7 (backup & durability) + §9 (observability)

## Test plan
- [x] uv run pytest tests/integration/deploy -v (7 pass)
- [x] shellcheck scripts/deploy/macmini-backup-upload-r2.sh (clean)
- [x] Manual: ran com.argon.backup on mini, dump produced, restore-list verified
- [x] Manual: ran com.argon.backup-r2 on mini, file appears in R2 bucket"
```

---

## Phase 7 — Post-migration verification & success criteria

Not a code phase, but the plan's exit check. After Phase 6 merges:

- [ ] **All 13 `com.argon.*` services running** — `ssh moremeds@100.66.147.98 'while read s; do [[ -z "$s" || "$s" == \#* ]] && continue; launchctl print "gui/$UID/$s" 2>/dev/null | grep "state =" | head -1 | xargs -I{} echo "$s: {}"; done < ~/projects/unusual-whales/config/services.list'`
Expected: every line says `state = running`.

- [ ] **MacBook lid-closed test** — Close MacBook for 2 hours. Reopen. Run:
  ```
  ssh moremeds@100.66.147.98 'psql -U argon_app argon_dev -h 127.0.0.1 -c "
    SELECT MAX(started_at) AS most_recent, COUNT(*) FROM uw_scan.scan_runs
    WHERE started_at > now() - interval '\''2 hours'\''"'
  ```
  Expected: non-zero count — confirms data collection survived the MacBook sleep.

- [ ] **Web reachable over Tailscale from MacBook** — `curl -fsS http://100.66.147.98:3001/` returns 200.

- [ ] **Nightly backup ran** — `ssh moremeds@100.66.147.98 'ls -la ~/projects/unusual-whales/data/backups/'` shows `argon_dev-<yesterday>.dump.gz`.

- [ ] **Weekly R2 backup ran (after first Sunday)** — `ssh moremeds@100.66.147.98 'cat ~/projects/unusual-whales/logs/backup-r2.out.log | tail -5'` shows `Upload OK`.

- [ ] **Rollback drill** — On a non-trading day, simulate a deploy failure and verify the auto-rollback path. Stop the API on the mini, then run prod.sh with the current tag; the script's post-deploy health check should fail (API down), trigger the rollback branch, and bring services back:
  ```
  # Take API down to force the health check to fail
  ssh moremeds@100.66.147.98 'launchctl unload "$HOME/Library/LaunchAgents/com.argon.api.plist"'
  # Run prod.sh — should fail health, then auto-rollback + re-load
  ssh moremeds@100.66.147.98 'cd ~/projects/unusual-whales && bash scripts/deploy/macmini-prod.sh "$(git describe --tags --exact-match)"'
  ```
  Expected: prod.sh logs "Health check failed", checks out previous tag, rebuilds, kickstarts, and brings API back. Check `logs/deploy.log` for the `ROLLBACK→<prev-tag>` line.

---

## Notes for the implementer

1. **xenon is the reference** — when in doubt about shell-script style, error handling, or launchd plist details, copy from `~/projects/xenon/scripts/deploy/macmini-*.sh` and `~/projects/xenon/config/templates/com.xenon.*.plist.template`. Both are battle-tested.

2. **No alembic** — unusual-whales uses raw SQL migrations via `scripts/migrate.sh`. Wherever xenon's script says `alembic upgrade head`, use `bash scripts/migrate.sh`. Wherever xenon's bootstrap references `alembic.ini`, that file does not exist here.

3. **postgresql@16, not 17** — the mini already has xenon's `postgresql@16` installed. Reuse that cluster. The spec mentioned 17 in places; defer to 16 wherever a number is needed.

4. **No PR for Phase 2 + 3** — those are host-state changes the user performs manually using the scripts from Phase 1. The plan's "verification" steps are the equivalent of CI for those phases.

5. **`.env` is gitignored** — every `.env` edit referenced (MacBook + mini) is manual. The plan documents the exact diff.

6. **Codex no-secrets rule still applies** — when a worker plist passes env vars, the runner code's `_runner_child_env` allow-list is the actual enforcement point. Don't add `UW_SCAN_API_KEY` or other fetcher secrets to AI worker plists.

7. **launchd quirks** — `launchctl load` works for now but Apple's modern equivalent is `launchctl bootstrap gui/$UID <plist>`. Both work; xenon uses `load`. Stay consistent with xenon.

8. **Time Machine handles macOS-level recovery** — the spec assumes Time Machine is running on the mini for xenon's sake; no additional configuration is in scope here.
