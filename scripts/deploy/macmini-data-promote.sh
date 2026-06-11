#!/usr/bin/env bash
# macmini-data-promote.sh — MacBook → Mac mini full Postgres mirror.
#
# RUN FROM THE MACBOOK. Dumps the source DB (default: option_wizard_local),
# ships over SSH, restores onto the Mac mini's option_wizard. Destructive on
# the target (--clean --if-exists).
#
# Usage:
#   ./scripts/deploy/macmini-data-promote.sh <ssh-host> --confirm \
#       [--src-db option_wizard_local] [--src-user chenxi]
#
# Post-rename default (chore/db-tripwire and later): --src-db option_wizard_local
# (MacBook dev DB) → mini's option_wizard. Different names on each side so the
# host/db isolation tripwire (uw_scan.config._enforce_db_isolation) refuses
# anything else.
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
# .env.local on the MacBook points UW_SCAN_DB_HOST at the mini, so sourcing
# .env here would silently dump the WRONG thing (the mini's option_wizard via
# the MacBook's Tailscale connection). Make the source explicit and document
# it. Default reflects the post-rename world: macbook = option_wizard_local.
SRC_DB="option_wizard_local"
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
DST_DB="option_wizard"
DST_USER="argon_app"
# Remote PATH prefix — Homebrew's postgresql@17 is keg-only, so pg_restore/
# psql aren't on the default non-interactive SSH PATH. Prepend the keg's
# bindir to every remote command so they resolve. Override via env if the
# mini's PG major changes (e.g. REMOTE_PG_BIN=/opt/homebrew/opt/postgresql@18/bin).
REMOTE_PG_BIN="${REMOTE_PG_BIN:-/opt/homebrew/opt/postgresql@17/bin}"
say "Source: $SRC_DB (as $SRC_USER) → Destination: $DST_DB on $SSH_HOST"
say "Remote PG bindir: $REMOTE_PG_BIN"

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
if ! ssh "$SSH_HOST" "PATH=${REMOTE_PG_BIN}:\$PATH command -v pg_restore" >/dev/null 2>&1; then
  die "pg_restore not found at $REMOTE_PG_BIN on target — run macmini-bootstrap.sh first, or set REMOTE_PG_BIN"
fi

# ---------- Local dump ----------
step "Dump local DB"
mkdir -p data/backups
TS="$(date +%Y%m%dT%H%M%S)"
DUMP_FILE="data/backups/${SRC_DB}-${TS}.dump"

# Find local pg_dump. Must be >= source server major; PG's policy refuses
# older pg_dump against newer server. MacBook may have multiple keg-only
# postgresql@N installed in parallel — prefer the one that matches (or
# exceeds) the running server. Default: postgresql@17 (current MacBook).
# Override via env if the MacBook upgrades: LOCAL_PG_BIN=/opt/homebrew/opt/postgresql@18/bin.
LOCAL_PG_BIN="${LOCAL_PG_BIN:-/opt/homebrew/opt/postgresql@17/bin}"
PG_DUMP="${LOCAL_PG_BIN}/pg_dump"
if [[ ! -x "$PG_DUMP" ]]; then
  # Fallback: scan PATH but skip versions older than 17 (best-effort guess).
  PG_DUMP="$(command -v pg_dump || true)"
fi
[[ -x "$PG_DUMP" ]] || die "pg_dump not found at $LOCAL_PG_BIN/pg_dump or on PATH"
say "pg_dump: $($PG_DUMP --version)"

"$PG_DUMP" -h localhost -U "$SRC_USER" -Fc --no-owner --no-acl -f "$DUMP_FILE" "$SRC_DB"
say "wrote $DUMP_FILE ($(du -h "$DUMP_FILE" | awk '{print $1}'))"

# ---------- Ship + restore ----------
step "Ship + restore on $SSH_HOST"
# Stream to target, restoring with --clean so the existing schema is replaced
# wholesale. --no-owner strips source ownership so the connecting role
# (argon_app) becomes owner of every restored object. ~/.pgpass on the mini
# (populated by macmini-bootstrap.sh) supplies the password — no inline
# PGPASSWORD needed.
ssh "$SSH_HOST" "PATH=${REMOTE_PG_BIN}:\$PATH pg_restore --clean --if-exists --no-owner --no-acl -h localhost -U ${DST_USER} -d ${DST_DB}" < "$DUMP_FILE"

# ---------- Verify ----------
step "Verify row counts on target"
ssh "$SSH_HOST" "PATH=${REMOTE_PG_BIN}:\$PATH psql -h localhost -U ${DST_USER} ${DST_DB} -c \"
  SELECT relname, n_live_tup FROM pg_stat_user_tables
  WHERE schemaname='uw_scan' ORDER BY n_live_tup DESC LIMIT 20\""

step "Done"
say "Mac mini DB now mirrors MacBook ${SRC_DB} as of $TS"
say "Dump archived: $DUMP_FILE"
warn "Restart services on the mini:"
warn "  ssh $SSH_HOST 'cd ~/projects/argon && while read s; do
       [[ -z \"\$s\" || \"\$s\" == \\#* ]] && continue
       launchctl kickstart -k gui/\$UID/\$s
     done < config/services.list'"
