#!/usr/bin/env bash
# macmini-prod.sh — recurring tag-based deploy on the Mac mini argon host.
#
# Usage:
#   ./scripts/deploy/macmini-prod.sh vX.Y.Z
#
# Behavior:
#   - Records the current tag as previous (for rollback)
#   - Fetches and checks out the new tag
#   - Syncs Python deps, installs web deps, builds web
#   - Runs SQL migrations (forward-only, idempotent)
#   - Kickstarts all com.argon.* launchd services from config/services.list
#   - Health-checks; if any fail, rolls back to the previous tag and re-kickstarts

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

TAG="${1:-}"
[[ -n "$TAG" ]] || { echo "usage: $0 vX.Y.Z" >&2; exit 2; }

say()  { printf '\033[1;34m[deploy]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[deploy]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[deploy] FAIL: %s\033[0m\n' "$*" >&2; exit 1; }
step() { printf '\n\033[1;36m=== %s ===\033[0m\n' "$*"; }

# Refuse to run anywhere but the argon host
[[ -f "$HOME/Library/LaunchAgents/com.argon.api.plist" ]] \
  || die "no com.argon.api launchd plist — run macmini-bootstrap.sh first"

# ---------- Record current tag for rollback ----------
PREV_TAG="$(git describe --tags --exact-match 2>/dev/null || git rev-parse HEAD)"
say "Current: $PREV_TAG  →  Target: $TAG"

# ---------- Refuse if working tree dirty ----------
git diff --quiet && git diff --cached --quiet \
  || die "working tree dirty — argon host must run a clean tag checkout"

# ---------- Checkout target ----------
step "Fetch + checkout $TAG"
git fetch --tags origin
git checkout "$TAG" || die "tag $TAG not found"
COMMIT="$(git rev-parse --short HEAD)"
say "HEAD now $COMMIT"

# ---------- Build ----------
build_release() {
  step "uv sync"
  uv sync --frozen --extra postgres

  step "npm install"
  (cd web && npm install --no-audit --no-fund --legacy-peer-deps)

  step "scripts/migrate.sh"
  bash scripts/migrate.sh

  step "web build"
  (cd web && npm run build)
}
build_release

# ---------- Kickstart services ----------
step "Kickstart launchd services"
while IFS= read -r label; do
  [[ -z "$label" || "$label" == \#* ]] && continue
  launchctl kickstart -k "gui/$UID/${label}"
  say "kickstart $label"
done < config/services.list

# ---------- Health checks ----------
step "Health checks"
sleep 5
check_url() {
  local url="$1" name="$2"
  for _ in {1..30}; do
    if curl -fsS --max-time 2 "$url" >/dev/null 2>&1; then
      say "✓ $name $url"
      return 0
    fi
    sleep 1
  done
  warn "✗ $name $url"
  return 1
}

if check_url "http://127.0.0.1:8400/health" "api" \
   && check_url "http://127.0.0.1:3001"      "web"; then
  step "Deploy OK: $TAG ($COMMIT)"
  printf '%s  %s  %s  OK\n' "$(date -u +%FT%TZ)" "$TAG" "$COMMIT" >> "$REPO_ROOT/logs/deploy.log"
  exit 0
fi

# ---------- Rollback ----------
warn "Health check failed — rolling back to $PREV_TAG"
git checkout "$PREV_TAG"
build_release
while IFS= read -r label; do
  [[ -z "$label" || "$label" == \#* ]] && continue
  launchctl kickstart -k "gui/$UID/${label}"
done < config/services.list
sleep 5
check_url "http://127.0.0.1:8400/health" "api(rollback)" || die "rollback ALSO failed — manual intervention required"
check_url "http://127.0.0.1:3001"        "web(rollback)" || die "rollback ALSO failed — manual intervention required"
printf '%s  %s  %s  ROLLBACK→%s\n' "$(date -u +%FT%TZ)" "$TAG" "$COMMIT" "$PREV_TAG" >> "$REPO_ROOT/logs/deploy.log"
die "deploy of $TAG failed; rolled back to $PREV_TAG"
