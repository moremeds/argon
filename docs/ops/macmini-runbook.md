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

1. On MacBook, flip `.env` (or `.env.local`) back:
   - `UW_SCAN_DB_HOST=127.0.0.1`
   - `UW_SCAN_DB_NAME=option_wizard` (MacBook's local DB was untouched)
   - `UW_SCAN_DB_USER=chenxi`
   - Remove the dev.sh guard tripwire trigger by virtue of localhost.
2. On MacBook, restore the original CLAUDE.md/etc via `git revert chore/rename-option-wizard-to-argon` (if that branch was already merged) or just keep the rename and override locally.
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
