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
#   - Seeds idempotent DB→DB datasets (market-tide sentiment) — no UW budget
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

# ---------- Tag <-> VERSION guard ----------
# The tag must match the checked-out VERSION (allow a -prerelease suffix, e.g.
# v0.1.0-rc1 on a VERSION=0.1.0 commit). Placed in the forward path only — the
# rollback path below checks out PREV_TAG (which may be a bare SHA) and must not
# trip this guard.
FILE_VERSION="$(cat VERSION)"
if [[ "$TAG" != "v$FILE_VERSION" && "$TAG" != "v$FILE_VERSION"-* ]]; then
  die "tag $TAG does not match checked-out VERSION (v$FILE_VERSION)"
fi
say "tag/VERSION OK: $TAG (v$FILE_VERSION)"

# ---------- Build ----------
build_release() {
  step "uv sync"
  uv sync --frozen --extra postgres

  step "npm ci"
  # npm ci: reproducible install from the committed lock; never rewrites
  # package-lock.json (npm install does, which self-dirties the tree and
  # blocks the next deploy's dirty-guard). ci.yml already uses npm ci.
  (cd web && rm -rf node_modules && npm ci --no-audit --no-fund --legacy-peer-deps)

  step "scripts/migrate.sh"
  bash scripts/migrate.sh

  step "web build"
  (cd web && npm run build)
}
build_release

# ---------- One-off data seed (post-migration) ----------
# Seed EOD market-tide sentiment for the full stored bar history so the
# slope→forward-return backtest has data the moment the feature ships. Pure
# DB→DB reshape of market_tide_snapshots (no UW budget spent). --if-empty makes
# it a true one-off: it seeds only when market_tide_sentiment_daily is empty, so
# re-running on every later release is an instant no-op; the nightly
# _market_tide_sentiment_eod job maintains it from then on. Best-effort: a
# failure here must NOT fail the deploy (the `if` keeps it exempt from set -e).
step "Seed market-tide sentiment (one-off)"
if uv run python scripts/backfill/market_tide_sentiment_backfill.py --if-empty; then
  say "✓ sentiment seed checked"
else
  warn "✗ sentiment seed failed (non-fatal — nightly job will recompute)"
fi

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
# check_url URL NAME [JQ_FILTER]
# Reachability check by default. With JQ_FILTER, the body must also satisfy it —
# needed because /api/health returns HTTP 200 even when the stack is broken, so a
# plain -fsS gate can never trip rollback.
#
# The gate asserts SERVING LIVENESS (what a deploy controls), NOT data freshness.
# It does NOT gate on `.ok`: `.ok` folds in `missed full scans`, which is routinely
# false for a benign reason — UW daily-budget exhaustion legitimately SKIPS full
# scans (see the budget governor), so the whole health goes ok=false most of the
# trading day. Gating deploy success on `.ok` deadlocks: neither the forward gate
# nor the rollback verify can pass, the script burns its retry budget and gtimeout
# kills it (rc=124). Worker/scan health is monitored separately (job_failures +
# heartbeats). So the gate checks db-up + the new VERSION actually serving.
check_url() {
  local url="$1" name="$2" filter="${3:-}"
  for _ in {1..30}; do
    if [[ -z "$filter" ]]; then
      if curl -fsS --max-time 2 "$url" >/dev/null 2>&1; then
        say "✓ $name $url"
        return 0
      fi
    else
      if curl -fsS --max-time 2 "$url" 2>/dev/null | jq -e "$filter" >/dev/null 2>&1; then
        say "✓ $name $url"
        return 0
      fi
    fi
    sleep 1
  done
  warn "✗ $name $url"
  return 1
}

if check_url "http://127.0.0.1:8400/api/health" "api" ".db == \"up\" and .version == \"$FILE_VERSION\"" \
   && check_url "http://127.0.0.1:3001"      "web"; then
  step "Deploy OK: $TAG ($COMMIT)"
  printf '%s  %s  %s  OK\n' "$(date -u +%FT%TZ)" "$TAG" "$COMMIT" >> "$REPO_ROOT/logs/deploy.log"
  # Authoritative "what's live" marker the deploy poller reads to decide whether
  # a newer release needs deploying. Only advanced on a *successful* deploy; a
  # rollback leaves it pointing at the last good release.
  printf '%s\n' "$TAG" > "$REPO_ROOT/logs/deployed_tag.txt"
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
check_url "http://127.0.0.1:8400/api/health" "api(rollback)" '.db == "up"' || die "rollback ALSO failed — manual intervention required"
check_url "http://127.0.0.1:3001"        "web(rollback)" || die "rollback ALSO failed — manual intervention required"
printf '%s  %s  %s  ROLLBACK→%s\n' "$(date -u +%FT%TZ)" "$TAG" "$COMMIT" "$PREV_TAG" >> "$REPO_ROOT/logs/deploy.log"
die "deploy of $TAG failed; rolled back to $PREV_TAG"
