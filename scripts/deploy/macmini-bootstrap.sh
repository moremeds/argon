#!/usr/bin/env bash
# macmini-bootstrap.sh — first-time setup for a fresh Mac mini argon host.
#
# Idempotent: every step probes current state and skips if already done. Safe
# to re-run after a partial failure.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/<owner>/argon/main/scripts/deploy/macmini-bootstrap.sh | bash
# or, after first clone:
#   ./scripts/deploy/macmini-bootstrap.sh
#
# Environment overrides (defaults shown):
#   ARGON_HOME=~/projects/argon                       # repo location
#   ARGON_REPO=git@github.com:<owner>/argon           # clone URL
#   ARGON_BRANCH=main                                 # branch/tag to check out at bootstrap
#   ARGON_PG_VERSION=16                               # Homebrew postgres version
#   ARGON_NODE_VERSION=22                             # Homebrew node version
#   ARGON_DB_NAME=option_wizard
#   ARGON_DB_NAME_TEST=option_wizard_test
#   ARGON_DB_ROLE=argon_app
#   ARGON_DB_PASSWORD=                       # auto-generated via openssl if unset
#
# What this script does NOT do (manual steps remain):
#   - Apple ID sign-in / FileVault enable / SSH key add to GitHub
#   - Codex CLI / Claude CLI install + 'claude /login' (script verifies presence + OAuth probe)
#   - UW / MASSIVE / FRED / R2 / DEEPSEEK secret values (you fill these into .env when prompted)
#   - Database promotion from MacBook (run scripts/deploy/macmini-data-promote.sh
#     from the MacBook after this finishes)

set -euo pipefail

# ---------- Config ----------
ARGON_HOME="${ARGON_HOME:-$HOME/projects/argon}"
ARGON_REPO="${ARGON_REPO:-git@github.com:moremeds/argon.git}"
ARGON_BRANCH="${ARGON_BRANCH:-main}"
ARGON_PG_VERSION="${ARGON_PG_VERSION:-16}"
ARGON_NODE_VERSION="${ARGON_NODE_VERSION:-22}"
ARGON_DB_NAME="${ARGON_DB_NAME:-option_wizard}"
ARGON_DB_NAME_TEST="${ARGON_DB_NAME_TEST:-option_wizard_test}"
ARGON_DB_ROLE="${ARGON_DB_ROLE:-argon_app}"
# Auto-generate a strong password on first run; reuse the existing one on
# re-runs by reading from .env (so the role's password stays the truth even
# if .env is regenerated). Safe characters only — no slash/plus/equals/quote
# that would need escaping in connection strings or pgpass lines.
if [[ -z "${ARGON_DB_PASSWORD:-}" ]]; then
  if [[ -f "${ARGON_HOME:-$HOME/projects/argon}/.env" ]] \
     && grep -qE '^UW_SCAN_DB_PASSWORD=.+' "${ARGON_HOME:-$HOME/projects/argon}/.env"; then
    ARGON_DB_PASSWORD="$(grep -E '^UW_SCAN_DB_PASSWORD=' "${ARGON_HOME:-$HOME/projects/argon}/.env" | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")"
  else
    ARGON_DB_PASSWORD="$(openssl rand -base64 24 | tr -d '/+=' | head -c 28)"
  fi
fi

USER_NAME="$(id -un)"

# ---------- Logging ----------
say()  { printf '\033[1;34m[bootstrap]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[bootstrap]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[bootstrap] FAIL: %s\033[0m\n' "$*" >&2; exit 1; }
step() { printf '\n\033[1;36m=== %s ===\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m  ✓\033[0m %s\n' "$*"; }
skip() { printf '\033[2m  ↩ skip: %s\033[0m\n' "$*"; }

# ---------- Preflight ----------
step "Preflight"
[[ "$(uname)" == "Darwin" ]] || die "This script targets macOS; got $(uname)"
arch="$(uname -m)"
[[ "$arch" == "arm64" ]] || warn "Non-Apple-Silicon arch ($arch). Brew prefix logic assumes /opt/homebrew."
ok "macOS $arch"

# ---------- Xcode Command Line Tools ----------
step "Xcode Command Line Tools"
if xcode-select -p >/dev/null 2>&1; then
  skip "CLT already installed at $(xcode-select -p)"
else
  say "Triggering CLT install (a GUI dialog will pop up)"
  xcode-select --install || true
  warn "Wait for the CLT dialog to finish, then re-run this script."
  exit 1
fi

# ---------- Homebrew ----------
step "Homebrew"
if command -v brew >/dev/null 2>&1; then
  ok "brew at $(command -v brew)"
else
  say "Installing Homebrew"
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  if [[ -d /opt/homebrew ]]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
  fi
fi

BREW_PREFIX="$(brew --prefix)"
ok "BREW_PREFIX=$BREW_PREFIX"

# ---------- Brew packages ----------
step "Brew packages"
brew_install() {
  local formula="$1"
  if brew list --formula "$formula" >/dev/null 2>&1; then
    skip "$formula"
  else
    say "brew install $formula"
    brew install "$formula"
  fi
}
brew_install "uv"
brew_install "node@${ARGON_NODE_VERSION}"
brew_install "postgresql@${ARGON_PG_VERSION}"
brew_install "git"
brew_install "gh"
# coreutils provides gtimeout, which the deploy poller uses to bound its
# `gh api` call (and the deploy itself). The live mini already has it; a fresh
# provision would otherwise fail `gtimeout: command not found` on the first poll.
brew_install "coreutils"

# Link node@N if not already on PATH as `node`
if ! command -v node >/dev/null 2>&1; then
  say "Linking node@${ARGON_NODE_VERSION}"
  brew link --force --overwrite "node@${ARGON_NODE_VERSION}"
fi
ok "node $(node --version)"
ok "uv $(uv --version)"

# ---------- Postgres service ----------
step "Postgres ${ARGON_PG_VERSION} service"
PG_BIN="${BREW_PREFIX}/opt/postgresql@${ARGON_PG_VERSION}/bin"
export PATH="${PG_BIN}:$PATH"

if brew services list | awk '{print $1, $2}' | grep -q "^postgresql@${ARGON_PG_VERSION} started$"; then
  skip "postgresql@${ARGON_PG_VERSION} already running"
else
  say "Starting postgresql@${ARGON_PG_VERSION}"
  brew services start "postgresql@${ARGON_PG_VERSION}"
  sleep 3
fi

# Wait for socket up to ~30s
for _ in {1..30}; do
  if "${PG_BIN}/pg_isready" -h localhost >/dev/null 2>&1; then break; fi
  sleep 1
done
"${PG_BIN}/pg_isready" -h localhost >/dev/null 2>&1 || die "Postgres not responding on localhost after 30s"
ok "Postgres up"

# ---------- DB role + databases ----------
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

# ---------- ~/.pgpass for non-interactive auth ----------
# psql/pg_dump/pg_restore on this mini (backup plist, restore commands in the
# ops runbook) should never need an inline PGPASSWORD. ~/.pgpass at mode 600
# is the Postgres-blessed credential store. Format: host:port:db:user:password.
step "Populating \$HOME/.pgpass for ${ARGON_DB_ROLE}"
PGPASS_FILE="$HOME/.pgpass"
touch "$PGPASS_FILE"
chmod 600 "$PGPASS_FILE"
# Replace any existing entries for this role + DB pair with the fresh password.
# `grep -v` filters out the matching lines; the new entries get appended.
TMP_PGPASS="$(mktemp)"
grep -vE "^(127\.0\.0\.1|localhost):5432:(${ARGON_DB_NAME}|${ARGON_DB_NAME_TEST}):${ARGON_DB_ROLE}:" \
  "$PGPASS_FILE" > "$TMP_PGPASS" || true
{
  cat "$TMP_PGPASS"
  printf '127.0.0.1:5432:%s:%s:%s\n' "${ARGON_DB_NAME}"      "${ARGON_DB_ROLE}" "${ARGON_DB_PASSWORD}"
  printf '127.0.0.1:5432:%s:%s:%s\n' "${ARGON_DB_NAME_TEST}" "${ARGON_DB_ROLE}" "${ARGON_DB_PASSWORD}"
  printf 'localhost:5432:%s:%s:%s\n' "${ARGON_DB_NAME}"      "${ARGON_DB_ROLE}" "${ARGON_DB_PASSWORD}"
  printf 'localhost:5432:%s:%s:%s\n' "${ARGON_DB_NAME_TEST}" "${ARGON_DB_ROLE}" "${ARGON_DB_PASSWORD}"
} > "$PGPASS_FILE"
chmod 600 "$PGPASS_FILE"
rm -f "$TMP_PGPASS"
ok "\$HOME/.pgpass populated"

# Sync password into the existing role (idempotent: takes effect every run, so
# rotating ARGON_DB_PASSWORD via env or re-running bootstrap propagates).
$PSQL -c "ALTER ROLE ${ARGON_DB_ROLE} WITH PASSWORD '${ARGON_DB_PASSWORD}';" >/dev/null
ok "role password synced"

# ---------- Repo clone ----------
step "Repo at ${ARGON_HOME}"
if [[ -d "${ARGON_HOME}/.git" ]]; then
  skip "repo already cloned"
  (cd "${ARGON_HOME}" && git fetch --tags origin && git checkout "${ARGON_BRANCH}" && git pull --ff-only)
else
  mkdir -p "$(dirname "${ARGON_HOME}")"
  say "Cloning ${ARGON_REPO}"
  if ! git clone "${ARGON_REPO}" "${ARGON_HOME}"; then
    warn "Clone failed. Likely no GitHub SSH key. Run: ssh-keygen -t ed25519 -C \"$USER_NAME@macmini\""
    warn "Then add the public key at https://github.com/settings/keys and re-run this script."
    exit 1
  fi
  (cd "${ARGON_HOME}" && git checkout "${ARGON_BRANCH}")
fi
cd "${ARGON_HOME}"
ok "repo at $(git rev-parse --short HEAD) on $(git symbolic-ref --short HEAD || echo detached)"

# ---------- Codex + Claude CLI auth verification (advisory) ----------
# These CLIs are used only by the ai-codex and ai-claude worker roles. The
# rest of the stack (API, web, uw/massive workers) doesn't depend on them.
# So probe-and-warn rather than probe-and-die: the affected worker plists
# stay un-loaded, the user gets a clear instruction to fix + reload, and the
# core services come up regardless. Each successful probe IS a paid API call;
# only runs on initial bootstrap.
step "Probe Codex CLI + Claude CLI auth for ${USER_NAME} (advisory)"
ai_claude_ok=1
ai_codex_ok=1

if ! command -v claude >/dev/null 2>&1; then
  warn "claude CLI not on PATH — ai-claude workers will be SKIPPED."
  warn "  Install Claude Code CLI on this host, run 'claude /login' as ${USER_NAME},"
  warn "  then reload the affected plists (instructions in summary)."
  ai_claude_ok=0
elif ! echo "respond with 'ok'" | claude --print --output-format text --max-turns 1 \
        --tools "" --disable-slash-commands --strict-mcp-config \
        --mcp-config '{"mcpServers": {}}' --no-session-persistence \
        >/dev/null 2>&1; then
  warn "claude --print probe failed — ai-claude workers will be SKIPPED."
  warn "  Run 'claude /login' as ${USER_NAME} in an interactive shell, then reload."
  ai_claude_ok=0
else
  ok "claude CLI signed in"
fi

if ! command -v codex >/dev/null 2>&1; then
  warn "codex CLI not on PATH — ai-codex workers will be SKIPPED."
  warn "  Install Codex CLI, authenticate, then reload the affected plists."
  ai_codex_ok=0
elif ! codex exec -s read-only --skip-git-repo-check "respond with ok" >/dev/null 2>&1; then
  warn "codex exec probe failed — ai-codex workers will be SKIPPED."
  warn "  Re-authenticate Codex CLI as ${USER_NAME} in an interactive shell, then reload."
  ai_codex_ok=0
else
  ok "codex CLI signed in"
fi

# ---------- .env scaffolding ----------
step ".env files"
if [[ ! -f "${ARGON_HOME}/.env" ]]; then
  say "Creating .env from .env.example (you must fill secrets before services start)"
  cp "${ARGON_HOME}/.env.example" "${ARGON_HOME}/.env"
  # The .env.example defaults are tuned for MacBook dev (HOST=127.0.0.1,
  # NAME=option_wizard_local). On the mini, same-host services use localhost
  # for Postgres and set the isolation override for the prodlike DB name.
  python3 - <<PY
from pathlib import Path
p = Path("${ARGON_HOME}/.env")
text = p.read_text()
text = text.replace("UW_SCAN_DB_HOST=127.0.0.1", "UW_SCAN_DB_HOST=127.0.0.1")
text = text.replace("UW_SCAN_DB_NAME=option_wizard_local", "UW_SCAN_DB_NAME=${ARGON_DB_NAME}")
text = text.replace("UW_SCAN_DB_USER=argon_app", "UW_SCAN_DB_USER=${ARGON_DB_ROLE}")
text = text.replace("UW_SCAN_DB_PASSWORD=", "UW_SCAN_DB_PASSWORD=${ARGON_DB_PASSWORD}", 1)
if "UW_SCAN_ALLOW_DB_MISMATCH=" not in text:
    text += "\nUW_SCAN_ALLOW_DB_MISMATCH=1\n"
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

# ---------- uv sync ----------
# argon's pyproject.toml only publishes the `postgres` extra; xenon's
# `--extra test` does NOT exist here. Add `--group dev` if you need pytest
# tooling on the mini; for prod, --extra postgres is sufficient.
step "uv sync (Python deps)"
(cd "${ARGON_HOME}" && uv sync --frozen --extra postgres)
ok "Python deps synced"

# ---------- Schema (deferred) ----------
# scripts/migrate.sh calls Settings.from_env() which raises if UW_SCAN_API_KEY
# is unset (src/uw_scan/config.py). On a fresh bootstrap, .env has DB defaults
# but secrets may still be empty. Skip migrate here — Phase 3 (pg_restore
# --clean --if-exists) brings the schema along with the data. For a greenfield
# install with no source DB, run `bash scripts/migrate.sh` manually after
# filling secrets.

# ---------- npm install + build ----------
# argon has only web/package.json (no root package.json).
step "Web build"
(cd "${ARGON_HOME}/web" && npm install --no-audit --no-fund --legacy-peer-deps)
(cd "${ARGON_HOME}/web" && npm run build)
ok "web built"

# ---------- launchd plists ----------
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
render_static_plist "com.argon.deploy-poller"

# Worker plists (5 roles × 2 indices = 10)
for role in uw massive ai-codex ai-claude ai-deepseek; do
  for index in 0 1; do
    render_worker_plist "$role" "$index"
  done
done

# Load: read services.list (excludes backup — calendar-scheduled, not kickstart-driven).
# Skip ai-claude and ai-codex worker plists when their CLI failed the auth
# probe above. They get rendered (so reload is one command) but stay unloaded
# so they don't crash-loop every ${ThrottleInterval}s.
skipped_labels=()
while IFS= read -r label; do
  [[ -z "$label" || "$label" == \#* ]] && continue
  if [[ "$label" == *"ai-claude"* ]] && [[ $ai_claude_ok -eq 0 ]]; then
    skipped_labels+=("$label")
    warn "skip load $label (claude auth missing)"
    continue
  fi
  if [[ "$label" == *"ai-codex"* ]] && [[ $ai_codex_ok -eq 0 ]]; then
    skipped_labels+=("$label")
    warn "skip load $label (codex auth missing)"
    continue
  fi
  plist="$HOME/Library/LaunchAgents/${label}.plist"
  # Bootstrap unloads (if loaded) then loads. Idempotent.
  launchctl unload "$plist" >/dev/null 2>&1 || true
  launchctl load "$plist"
  ok "loaded $label"
done < "${ARGON_HOME}/config/services.list"

# Backup plist is rendered but NOT loaded here — that happens in Phase 6.

# Deploy poller: rendered + loaded but kept OUT of services.list. It is the
# thing that PERFORMS deploys (runs macmini-prod.sh), so it must never be
# kickstarted as part of an app deploy — same exclusion rationale as the backup
# plist. StartInterval drives it; it polls GitHub for new Releases every 120s.
poller_plist="$HOME/Library/LaunchAgents/com.argon.deploy-poller.plist"
launchctl unload "$poller_plist" >/dev/null 2>&1 || true
launchctl load "$poller_plist"
ok "loaded com.argon.deploy-poller"

# ---------- Health checks ----------
step "Health checks"
sleep 5

check_url() {
  local url="$1" name="$2"
  for _ in {1..20}; do
    if curl -fsS --max-time 2 "$url" >/dev/null 2>&1; then
      ok "$name reachable: $url"
      return 0
    fi
    sleep 1
  done
  warn "$name NOT reachable at $url after 20s — check logs/${name}.err.log"
  return 1
}

api_ok=0; web_ok=0; db_ok=0
# Actual route is /api/health (registered in routers/health.py); /health 404s.
# Note: this endpoint queries uw_scan.worker_heartbeat — returns 500 until the
# schema is populated (Phase 3 data-promote). That's expected at this point.
check_url "http://127.0.0.1:8400/api/health" "api" && api_ok=1 || true
check_url "http://127.0.0.1:3001"        "web" && web_ok=1 || true
# ~/.pgpass (written above) supplies the password — no inline PGPASSWORD needed.
if "${PG_BIN}/psql" \
     -h localhost -U "${ARGON_DB_ROLE}" "${ARGON_DB_NAME}" \
     -c "SELECT COUNT(*) FROM uw_scan.scan_runs" >/dev/null 2>&1; then
  db_ok=1
fi
# db_ok=0 on a freshly-bootstrapped mini is expected — the schema doesn't
# exist until Phase 3 promote runs.

# ---------- Summary ----------
step "Bootstrap summary"
printf '  Repo:           %s\n' "${ARGON_HOME}"
printf '  Database:       %s, %s @ localhost:5432\n' "${ARGON_DB_NAME}" "${ARGON_DB_NAME_TEST}"
printf '  DB role:        %s (NOSUPERUSER NOCREATEDB NOCREATEROLE)\n' "${ARGON_DB_ROLE}"
printf '  API:            %s\n' "$([[ $api_ok == 1 ]] && echo UP || echo DOWN)"
printf '  Web:            %s\n' "$([[ $web_ok == 1 ]] && echo UP || echo DOWN)"
printf '  Schema present: %s\n' "$([[ $db_ok == 1 ]] && echo YES || echo 'NO (run promote to populate)')"
printf '  AI workers:     claude=%s codex=%s\n' \
  "$([[ $ai_claude_ok == 1 ]] && echo READY || echo SKIPPED)" \
  "$([[ $ai_codex_ok == 1 ]] && echo READY || echo SKIPPED)"

if (( ${#skipped_labels[@]} > 0 )); then
  printf '\n  \033[1;33mSkipped plists (fix auth, then reload each):\033[0m\n'
  for label in "${skipped_labels[@]}"; do
    # shellcheck disable=SC2016
    # Intentional literal $HOME — user pastes this and expands at their shell.
    printf '    launchctl load $HOME/Library/LaunchAgents/%s.plist\n' "$label"
  done
fi

cat <<NEXT

== ${ARGON_DB_ROLE} password (copy to MacBook .env.local) ==
${ARGON_DB_PASSWORD}
==========================================================
  (Stored in ${ARGON_HOME}/.env as UW_SCAN_DB_PASSWORD and in ~/.pgpass.
   ${USER_NAME}@mini does not need this string at runtime — it's in .env. But
   when you point a MacBook at the mini via .env.local, you'll need to set
   UW_SCAN_DB_PASSWORD to this value there too.)

Next steps:
  1. Promote data from MacBook:
     # on the MacBook:
     ./scripts/deploy/macmini-data-promote.sh moremeds@100.66.147.98 --confirm

  2. Point MacBook at mini (when ready):
     # on the MacBook, in .env.local (gitignored):
     UW_SCAN_DB_HOST=100.66.147.98
     UW_SCAN_DB_NAME=${ARGON_DB_NAME}
     UW_SCAN_DB_USER=${ARGON_DB_ROLE}
     UW_SCAN_DB_PASSWORD=${ARGON_DB_PASSWORD}

  3. Tail logs:
     tail -f logs/*.err.log

NEXT
[[ $api_ok == 1 && $web_ok == 1 ]] || exit 1
