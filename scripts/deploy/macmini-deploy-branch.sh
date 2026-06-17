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
# PATH prefix: non-interactive SSH doesn't source ~/.zprofile, so Homebrew-
# installed CLIs (uv) and the keg-only postgresql@17 psql aren't on PATH.
# Mirror the PATH that com.argon.worker plists already use, plus the
# postgresql@17 bindir for migrate.sh.
REMOTE_CMD='export PATH="/opt/homebrew/bin:/opt/homebrew/opt/postgresql@17/bin:/usr/local/bin:/usr/bin:/bin"
'"set -euo pipefail
cd ~/projects/argon
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
cd web && npm ci --legacy-peer-deps --no-audit --no-fund && npm run build && cd .."
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
for endpoint in "http://100.66.147.98:8400/api/health?source=uw" "http://100.66.147.98:3001"; do
  # API takes ~3-5s to bind after launchctl kickstart; brief retry loop avoids
  # racing the warm-up window.
  if curl -fsS --max-time 5 --retry 4 --retry-delay 2 --retry-connrefused "$endpoint" >/dev/null 2>&1; then
    say "  ✓ $endpoint"
  else
    die "  ✗ $endpoint (check ssh $SSH_HOST 'tail logs/api.err.log logs/web.err.log')"
  fi
done

say "Done. Branch $BRANCH live on $SSH_HOST."
