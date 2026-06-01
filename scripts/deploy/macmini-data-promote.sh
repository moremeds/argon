#!/usr/bin/env bash
# macmini-data-promote.sh — MacBook → Mac mini full Postgres mirror.
#
# RUN FROM THE MACBOOK. Dumps the source DB (default: option_wizard), ships
# over SSH, restores onto the Mac mini's argon_dev. Destructive on the target
# (--clean --if-exists).
#
# Usage:
#   ./scripts/deploy/macmini-data-promote.sh <ssh-host> --confirm \
#       [--src-db option_wizard] [--src-user chenxi]
#
# Phase 3 cutover: --src-db option_wizard (pre-migration MacBook DB).
# Ad-hoc re-mirror later: --src-db argon_dev_macbook (or whatever your local
# rollback-insurance DB is named); only sensible if you maintain a local
# Postgres post-migration.
#
# Example:
#   ./scripts/deploy/macmini-data-promote.sh moremeds@100.66.147.98 --confirm
#
# Safety:
#   - Refuses if FastAPI (8400), web (3001), or worker schedulers are running
#     on the MacBook — those are writers and mid-snapshot is corrupt
#   - Refuses without --confirm
#   - Saves dump to data/backups/ with timestamp before shipping (audit trail)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

SSH_HOST="${1:-}"
CONFIRM="${2:-}"
[[ -n "$SSH_HOST" ]] || { echo "usage: $0 <ssh-host> --confirm [--src-db NAME] [--src-user USER]" >&2; exit 2; }

say()  { printf '\033[1;34m[promote]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[promote]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[promote] FAIL: %s\033[0m\n' "$*" >&2; exit 1; }
step() { printf '\n\033[1;36m=== %s ===\033[0m\n' "$*"; }

# ---------- Source DB explicit (not inferred from .env) ----------
# Phase 4 changes MacBook's .env to point UW_SCAN_DB_NAME=argon_dev
# UW_SCAN_DB_USER=argon_app; after that, sourcing those defaults would dump
# the WRONG thing (try to dump the mini's argon_dev via MacBook's connection).
# Make the source explicit and document it.
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

# ---------- Refuse if local writers running ----------
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

# ---------- Confirm destructive op ----------
if [[ "$CONFIRM" != "--confirm" ]]; then
  warn "This will OVERWRITE Mac mini DB '$DST_DB' on $SSH_HOST."
  warn "Re-run with --confirm to proceed."
  exit 1
fi

# ---------- Probe target DB ----------
step "Probe target Postgres on $SSH_HOST"
if ! ssh "$SSH_HOST" "command -v pg_restore" >/dev/null 2>&1; then
  die "pg_restore not on PATH on target — run macmini-bootstrap.sh first"
fi

# ---------- Local dump ----------
step "Dump local DB"
mkdir -p data/backups
TS="$(date +%Y%m%dT%H%M%S)"
DUMP_FILE="data/backups/${SRC_DB}-${TS}.dump"

# Find local pg_dump (Homebrew layout)
PG_DUMP="$(command -v pg_dump || true)"
[[ -x "$PG_DUMP" ]] || PG_DUMP="/opt/homebrew/opt/postgresql@16/bin/pg_dump"
[[ -x "$PG_DUMP" ]] || die "pg_dump not found"

"$PG_DUMP" -h localhost -U "$SRC_USER" -Fc --no-owner --no-acl -f "$DUMP_FILE" "$SRC_DB"
say "wrote $DUMP_FILE ($(du -h "$DUMP_FILE" | awk '{print $1}'))"

# ---------- Ship + restore ----------
step "Ship + restore on $SSH_HOST"
# Stream to target, restoring with --clean so the existing schema is replaced
# wholesale. --no-owner strips source ownership so the connecting role
# (argon_app) becomes owner of every restored object.
ssh "$SSH_HOST" "PGPASSWORD='argon_dev' pg_restore --clean --if-exists --no-owner --no-acl -h localhost -U ${DST_USER} -d ${DST_DB}" < "$DUMP_FILE"

# ---------- Verify ----------
step "Verify row counts on target"
ssh "$SSH_HOST" "PGPASSWORD='argon_dev' psql -h localhost -U ${DST_USER} ${DST_DB} -c \"
  SELECT relname, n_live_tup FROM pg_stat_user_tables
  WHERE schemaname='uw_scan' ORDER BY n_live_tup DESC LIMIT 20\""

step "Done"
say "Mac mini DB now mirrors MacBook ${SRC_DB} as of $TS"
say "Dump archived: $DUMP_FILE"
warn "Restart services on the mini:"
warn "  ssh $SSH_HOST 'cd ~/projects/unusual-whales && while read s; do
       [[ -z \"\$s\" || \"\$s\" == \\#* ]] && continue
       launchctl kickstart -k gui/\$UID/\$s
     done < config/services.list'"
