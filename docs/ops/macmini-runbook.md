# Mac Mini Ops Runbook (argon stack)

**Host:** Mac mini @ Tailscale `100.66.147.98`, SSH user `moremeds`.
**Repo:** `~/projects/argon` on mini.
**Services:** 13 launchd jobs (`com.argon.*`) + 2 backup jobs (`com.argon.backup`, `com.argon.backup-r2`).
**Co-tenant:** xenon shares the mini's Homebrew Postgres cluster (currently `postgresql@17`, port 5432; separate DBs/roles). Bootstrap probes whatever `brew services` reports running, so a future major bump is transparent to argon.
**Spec:** `docs/superpowers/specs/2026-06-01-mac-mini-stack-migration-design.md`
**Plan:** `docs/superpowers/plans/2026-06-01-mac-mini-stack-migration-plan.md`

## First-time setup

Run on the mini as `moremeds`:
```
bash scripts/deploy/macmini-bootstrap.sh
```
Idempotent; safe to re-run.

**Claude/Codex CLI auth is advisory.** Bootstrap probes both CLIs but does not gate the core stack on them. If either probe fails (CLI missing, not signed in, keychain inaccessible), the corresponding `ai-claude` / `ai-codex` worker plists are **rendered but not loaded** — so they don't crash-loop. The bootstrap summary prints the exact `launchctl load …` commands to run after fixing the auth. AI-DeepSeek workers depend on `DEEPSEEK_API_KEY` in `.env`, not a CLI; the standard "fill secrets" step covers them.

## Regular deploy of a tagged release

From MacBook:
```
ssh moremeds@100.66.147.98 'cd ~/projects/argon && bash scripts/deploy/macmini-prod.sh v1.2.3'
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

- Nightly local: `com.argon.backup` (03:00) writes `data/backups/option_wizard-<date>.dump.gz`, retains 7 days.
- Weekly R2: `com.argon.backup-r2` (Sundays 04:00) uploads to `s3://${R2_BUCKET}/postgres/`.

**Note on auth:** The mini's `~/.pgpass` (mode 600, populated by `macmini-bootstrap.sh`) supplies the `argon_app` password for `127.0.0.1:5432`. None of the commands below need an inline `PGPASSWORD=...`. If you need to operate from a different host or as a different user, either populate `~/.pgpass` for that user or set `PGPASSWORD` inline (the password is in `${ARGON_HOME}/.env` on the mini as `UW_SCAN_DB_PASSWORD`).

Restore from local dump:
```
ssh moremeds@100.66.147.98 'cd ~/projects/argon
  latest=$(ls -1t data/backups/option_wizard-*.dump.gz | head -1)
  echo "Restoring from $latest"
  gunzip -c "$latest" \
    | pg_restore --clean --if-exists --no-owner --no-acl \
      -h 127.0.0.1 -U argon_app -d option_wizard'
```

Restore from R2:
```
ssh moremeds@100.66.147.98 'cd ~/projects/argon && set -a; source .env; set +a
  AWS_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID" AWS_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY" \
    aws s3 cp s3://${R2_BUCKET}/postgres/option_wizard-2026-06-01.dump.gz - \
      --endpoint-url "${R2_ENDPOINT_OVERRIDE:-https://${R2_ACCOUNT_ID}.r2.cloudflarestorage.com}" \
    | gunzip | pg_restore --clean --if-exists --no-owner --no-acl \
      -h 127.0.0.1 -U argon_app -d option_wizard'
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
ssh moremeds@100.66.147.98 'cd ~/projects/argon && while IFS= read -r s; do
  [[ -z "$s" || "$s" == \#* ]] && continue
  launchctl kickstart -k "gui/$UID/$s"
done < config/services.list'
```

Stop all 13 (e.g., for maintenance) — uses `unload` to match xenon's `load`/`unload` pattern in the bootstrap script. **Note:** `com.argon.massive-ws` holds an in-memory `TickBuffer` (see `src/uw_scan/worker/ws_tick_buffer.py`); SIGTERM from `unload` discards anything not yet flushed (~5-30 s of intraday ticks during RTH). For ops where data continuity matters, prefer maintenance windows in pre-market or after-hours.
```
ssh moremeds@100.66.147.98 'while IFS= read -r s; do
  [[ -z "$s" || "$s" == \#* ]] && continue
  launchctl unload "$HOME/Library/LaunchAgents/$s.plist" 2>/dev/null
done < ~/projects/argon/config/services.list'
```

Re-load all 13 (after an unload):
```
ssh moremeds@100.66.147.98 'while IFS= read -r s; do
  [[ -z "$s" || "$s" == \#* ]] && continue
  launchctl load "$HOME/Library/LaunchAgents/$s.plist"
done < ~/projects/argon/config/services.list'
```

## Logs

- Aggregate: `ssh moremeds@100.66.147.98 'cd ~/projects/argon && tail -F logs/*.err.log'`
- API only: `ssh moremeds@100.66.147.98 'tail -F ~/projects/argon/logs/api.err.log'`
- One worker: `ssh moremeds@100.66.147.98 'tail -F ~/projects/argon/logs/worker-ai-claude-0.err.log'`

## Health checks

From MacBook over Tailscale:
```
curl -fsS http://100.66.147.98:8400/health | jq .
curl -fsSI http://100.66.147.98:3001 | head -1
psql -h 100.66.147.98 -U argon_app -d option_wizard -c "SELECT COUNT(*) FROM uw_scan.scan_runs"
```

## Rollback (mini-stack-wide, in case migration was a mistake)

1. On MacBook, flip `.env` (or delete `.env.local`) back:
   - `UW_SCAN_DB_HOST=127.0.0.1`
   - `UW_SCAN_DB_NAME=option_wizard` (MacBook's local DB was untouched)
   - `UW_SCAN_DB_USER=chenxi` (MacBook's local DB owner; mini's `argon_app` only owns the mini-side copy)
   - Remove `UW_SCAN_DB_PASSWORD` (local socket auth doesn't need it).
   - dev.sh guard auto-clears (no longer pointing at mini).
2. On mini, stop all services:
   ```
   ssh moremeds@100.66.147.98 'while read -r s; do
     [[ -z "$s" || "$s" == \#* ]] && continue
     launchctl unload "$HOME/Library/LaunchAgents/$s.plist" 2>/dev/null
   done < ~/projects/argon/config/services.list'
   ```
3. On mini, optionally drop the DBs + role (only if abandoning entirely):
   ```
   ssh moremeds@100.66.147.98 'psql postgres -c "
     DROP DATABASE IF EXISTS option_wizard;
     DROP DATABASE IF EXISTS option_wizard_test;
     DROP ROLE IF EXISTS argon_app;"'
   ```
4. Restart MacBook's `scripts/dev.sh`.

xenon is unaffected — different DBs, different roles, different launchd labels.
