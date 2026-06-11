#!/usr/bin/env bash
# scripts/dev.sh — run Next.js, FastAPI, and sharded worker schedulers concurrently.
# Uses npx concurrently from the web/ package so we don't add a top-level node dep.
set -euo pipefail

cd "$(dirname "$0")/.."

# ---- Mac mini cutover tripwire (shell layer) ----
# Refuse to spawn local workers if .env / .env.local point UW_SCAN_DB_HOST at
# the mini (100.66.147.98). Two writers (MacBook + mini) on the same queue
# would race via FOR UPDATE SKIP LOCKED and double-charge AI providers.
# The stronger (host, db_name) check lives in uw_scan.config._enforce_db_isolation;
# this shell-level check exits earlier (before npm/uv start) and complements it.
# Override with UW_SCAN_ALLOW_DEV_AGAINST_MINI=1 if you really want to debug
# against mini state (read-only browser session, no workers expected).
_env_var() {
  local key="$1" f="$2"
  [[ -f "$f" ]] || { echo ""; return; }
  grep -E "^[[:space:]]*${key}=" "$f" \
    | tail -1 | cut -d= -f2 | tr -d '"' | tr -d "'" | xargs
}
_resolve_env_var() {
  local key="$1" current="${!1:-}"
  if [[ -n "$current" ]]; then echo "$current"; return; fi
  local v
  v="$(_env_var "$key" .env.local)"
  [[ -n "$v" ]] || v="$(_env_var "$key" .env)"
  echo "$v"
}
db_host="$(_resolve_env_var UW_SCAN_DB_HOST)"
db_name="$(_resolve_env_var UW_SCAN_DB_NAME)"
: "${db_host:=127.0.0.1}"
: "${db_name:=option_wizard_local}"
printf '[dev.sh] Resolved DB: host=%s db_name=%s\n' "$db_host" "$db_name" >&2

if [[ "$db_host" == "100.66.147.98" ]] && [[ "${UW_SCAN_ALLOW_DEV_AGAINST_MINI:-0}" != "1" ]]; then
  cat >&2 <<EOF
[dev.sh] REFUSING to spawn workers against the mini DB at $db_host.
[dev.sh] Two writers (MacBook + mini) on the same queue would race via
[dev.sh] FOR UPDATE SKIP LOCKED and double-charge AI providers.
[dev.sh]
[dev.sh] If you really mean to point dev.sh at the mini, set:
[dev.sh]   UW_SCAN_ALLOW_DEV_AGAINST_MINI=1 bash scripts/dev.sh
[dev.sh]
[dev.sh] Normal MacBook dev: revert .env.local to a local Postgres
[dev.sh] (UW_SCAN_DB_HOST=127.0.0.1 + UW_SCAN_DB_NAME=option_wizard_local)
[dev.sh] or delete .env.local entirely.
EOF
  exit 1
fi

# Ensure web/ deps are installed (cheap if already cached).
if [ ! -d web/node_modules ]; then
  ( cd web && npm install )
fi

# Color-prefixed concurrent run. Press Ctrl-C to stop all processes.
# Shared count exports so the API process can enumerate worker rows in the
# health panel. AI workers use FOR UPDATE SKIP LOCKED on the analysis queue,
# so 2 instances safely process distinct tickers in parallel.
COUNTS="UW_SCAN_UW_WORKER_COUNT=2 UW_SCAN_MASSIVE_WORKER_COUNT=2 UW_SCAN_AI_WORKER_COUNT=2 TRADE_INSIGHTS_AI_CODEX_WORKER_COUNT=2 TRADE_INSIGHTS_AI_CLAUDE_WORKER_COUNT=2"
# Single source of truth for WS-pipeline mode. Exported to API + every worker
# so scheduler closures (full_scan / rescan) see the same value (R6 — without
# this the UW workers would still write UW-derived spot over the WS values).
# XENON_WS_ENABLED makes xenon's IB realtime WS the primary spot feed with
# massive as automatic fallback; if no xenon server is reachable the consumer
# fails over within seconds, so defaulting it on is harmless. Point at a
# remote xenon (e.g. the mini) via XENON_WS_URL in .env.local.
WS="MASSIVE_WS_ENABLED=true XENON_WS_ENABLED=${XENON_WS_ENABLED:-true}"

exec npx --prefix web concurrently \
  -n next,api,uw-0,uw-1,massive-0,massive-1,ai-codex-0,ai-codex-1,ai-claude-0,ai-claude-1,ai-deepseek-0,ai-deepseek-1,massive-ws \
  -c cyan,green,yellow,magenta,blue,white,red,red,gray,gray,brightMagenta,brightMagenta,brightCyan \
  "cd web && npm run dev" \
  "$COUNTS $WS uv run uvicorn uw_scan.api.server:app --host 127.0.0.1 --port 8400 --reload --reload-dir src" \
  "$COUNTS $WS UW_SCAN_WORKER_ROLE=uw UW_SCAN_WORKER_INDEX=0 UW_SCAN_WORKER_COUNT=2 uv run python -m uw_scan.worker.scheduler" \
  "$COUNTS $WS UW_SCAN_WORKER_ROLE=uw UW_SCAN_WORKER_INDEX=1 UW_SCAN_WORKER_COUNT=2 uv run python -m uw_scan.worker.scheduler" \
  "$COUNTS $WS UW_SCAN_WORKER_ROLE=massive UW_SCAN_WORKER_INDEX=0 UW_SCAN_WORKER_COUNT=2 uv run python -m uw_scan.worker.scheduler" \
  "$COUNTS $WS UW_SCAN_WORKER_ROLE=massive UW_SCAN_WORKER_INDEX=1 UW_SCAN_WORKER_COUNT=2 uv run python -m uw_scan.worker.scheduler" \
  "$COUNTS $WS UW_SCAN_WORKER_ROLE=ai-codex    UW_SCAN_WORKER_INDEX=0 UW_SCAN_WORKER_COUNT=2 uv run python -m uw_scan.worker.scheduler" \
  "$COUNTS $WS UW_SCAN_WORKER_ROLE=ai-codex    UW_SCAN_WORKER_INDEX=1 UW_SCAN_WORKER_COUNT=2 uv run python -m uw_scan.worker.scheduler" \
  "$COUNTS $WS UW_SCAN_WORKER_ROLE=ai-claude   UW_SCAN_WORKER_INDEX=0 UW_SCAN_WORKER_COUNT=2 uv run python -m uw_scan.worker.scheduler" \
  "$COUNTS $WS UW_SCAN_WORKER_ROLE=ai-claude   UW_SCAN_WORKER_INDEX=1 UW_SCAN_WORKER_COUNT=2 uv run python -m uw_scan.worker.scheduler" \
  "$COUNTS $WS UW_SCAN_WORKER_ROLE=ai-deepseek UW_SCAN_WORKER_INDEX=0 UW_SCAN_WORKER_COUNT=2 uv run python -m uw_scan.worker.scheduler" \
  "$COUNTS $WS UW_SCAN_WORKER_ROLE=ai-deepseek UW_SCAN_WORKER_INDEX=1 UW_SCAN_WORKER_COUNT=2 uv run python -m uw_scan.worker.scheduler" \
  "$COUNTS $WS uv run python -m uw_scan.worker.massive_ws_consumer"
