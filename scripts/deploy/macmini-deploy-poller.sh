#!/usr/bin/env bash
# macmini-deploy-poller.sh — RUN ON THE MAC MINI (launchd com.argon.deploy-poller).
#
# Pull-based deploy trigger — the launchd equivalent of xenon's Watchtower. Poll
# the latest *published, non-prerelease* GitHub Release; if its tag differs from
# what's deployed (logs/deployed_tag.txt), run macmini-prod.sh to deploy it.
#
# Gating on the Release (not the raw tag) means we only ever deploy a version
# that release.yml's verify job already proved green — the Release is created in
# the publish job, after verify passes. Prereleases are excluded by the API.
#
# Flags:
#   --dry-run    print the decision, deploy nothing
#   --once       single pass (default; launchd re-invokes on StartInterval)

set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

REPO="moremeds/argon"
DEPLOYED_FILE="$REPO_ROOT/logs/deployed_tag.txt"
FAILED_FILE="$REPO_ROOT/logs/deploy-poller.failed_tag"
LOCK="$REPO_ROOT/logs/deploy-poller.lock"

DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --once) ;;  # default; accepted for clarity
    *) echo "unknown arg: $arg" >&2; exit 2 ;;
  esac
done

say() { printf '%s [poller] %s\n' "$(date -u +%FT%TZ)" "$*"; }

mkdir -p "$REPO_ROOT/logs"

# 1. Latest published non-prerelease Release tag. Distinguish "no release yet"
#    (404 — normal, quiet) from a real gh auth/network failure (loud WARN, so a
#    silently-expired gh token doesn't make the mini stop deploying unnoticed).
gh_err="$(mktemp)"
latest="$(gtimeout 30 gh api "repos/${REPO}/releases/latest" --jq '.tag_name' 2>"$gh_err")" || latest=""
if [[ -z "$latest" ]]; then
  if grep -qi 'not found\|404' "$gh_err"; then
    say "no published release yet — skip"
  else
    say "WARN: gh api failed (auth/network?) — NOT deploying. stderr: $(tr '\n' ' ' < "$gh_err" | head -c 200)"
  fi
  rm -f "$gh_err"
  exit 0
fi
rm -f "$gh_err"

deployed=""
[[ -f "$DEPLOYED_FILE" ]] && deployed="$(cat "$DEPLOYED_FILE")"
if [[ "$latest" == "$deployed" ]]; then
  say "up to date ($deployed)"
  exit 0
fi

failed=""
[[ -f "$FAILED_FILE" ]] && failed="$(cat "$FAILED_FILE")"
if [[ "$latest" == "$failed" ]]; then
  say "release $latest previously FAILED to deploy — skipping until a newer release (manual intervention needed)"
  exit 0
fi

# Dirty-tree guard: never destructively clean (CLAUDE.md bans reset --hard /
# checkout -f). After the Component 0 fix the tree stays clean, so a dirty tree
# here is a genuine anomaly — alert and skip.
if ! git diff --quiet || ! git diff --cached --quiet; then
  say "ALERT: working tree dirty — refusing to auto-deploy $latest. Resolve on the mini, then it deploys next tick."
  exit 0
fi

if [[ "$DRY_RUN" -eq 1 ]]; then
  say "[dry-run] would deploy $latest (deployed=${deployed:-none})"
  exit 0
fi

say "deploying $latest (was ${deployed:-none})"
# gtimeout 1800 bounds a hung deploy (e.g. uv sync / npm ci stalling on the
# network) so a stuck build can't hold the lock forever — a timeout surfaces as
# rc=124 and is treated as a failed deploy below. lockf -t 0 is the lock: it
# AUTO-RELEASES if this process dies (crash-safe, unlike a mkdir-based lock that
# would leave a stale dir), and returns EX_TEMPFAIL=75 only when the lock is
# held. macmini-prod.sh itself only ever exits 0/1/2 (verified), so 75 is an
# unambiguous "lock held" signal and cannot be confused with a real failure.
set +e
gtimeout 1800 /usr/bin/lockf -t 0 "$LOCK" bash "$REPO_ROOT/scripts/deploy/macmini-prod.sh" "$latest"
rc=$?
set -e
if [[ $rc -eq 0 ]]; then
  say "deploy of $latest OK"
  rm -f "$FAILED_FILE"
  exit 0
fi
if [[ $rc -eq 75 ]]; then
  # lockf EX_TEMPFAIL: a deploy is already running. Try again next tick.
  say "another deploy in progress (lock held) — retry next tick"
  exit 0
fi
say "deploy of $latest FAILED (rc=$rc) — macmini-prod.sh self-rolled-back (rc=124 = timed out); marking failed"
echo "$latest" > "$FAILED_FILE"
exit 1
