#!/usr/bin/env bash
# scripts/dev.sh — run Next.js, FastAPI, and sharded worker schedulers concurrently.
# Uses npx concurrently from the web/ package so we don't add a top-level node dep.
set -euo pipefail

cd "$(dirname "$0")/.."

# Ensure web/ deps are installed (cheap if already cached).
if [ ! -d web/node_modules ]; then
  ( cd web && npm install )
fi

# Color-prefixed concurrent run. Press Ctrl-C to stop all processes.
# Shared count exports so the API process can enumerate worker rows in the
# health panel. AI workers use FOR UPDATE SKIP LOCKED on the analysis queue,
# so 2 instances safely process distinct tickers in parallel.
COUNTS="UW_SCAN_UW_WORKER_COUNT=2 UW_SCAN_MASSIVE_WORKER_COUNT=2 UW_SCAN_AI_WORKER_COUNT=2"

exec npx --prefix web concurrently \
  -n next,api,uw-0,uw-1,massive-0,massive-1,ai-0,ai-1 \
  -c cyan,green,yellow,magenta,blue,white,red,gray \
  "cd web && npm run dev" \
  "$COUNTS uv run uvicorn uw_scan.api.server:app --host 127.0.0.1 --port 8400 --reload --reload-dir src" \
  "$COUNTS UW_SCAN_WORKER_ROLE=uw UW_SCAN_WORKER_INDEX=0 UW_SCAN_WORKER_COUNT=2 uv run python -m uw_scan.worker.scheduler" \
  "$COUNTS UW_SCAN_WORKER_ROLE=uw UW_SCAN_WORKER_INDEX=1 UW_SCAN_WORKER_COUNT=2 uv run python -m uw_scan.worker.scheduler" \
  "$COUNTS UW_SCAN_WORKER_ROLE=massive UW_SCAN_WORKER_INDEX=0 UW_SCAN_WORKER_COUNT=2 uv run python -m uw_scan.worker.scheduler" \
  "$COUNTS UW_SCAN_WORKER_ROLE=massive UW_SCAN_WORKER_INDEX=1 UW_SCAN_WORKER_COUNT=2 uv run python -m uw_scan.worker.scheduler" \
  "$COUNTS UW_SCAN_WORKER_ROLE=ai UW_SCAN_WORKER_INDEX=0 UW_SCAN_WORKER_COUNT=2 uv run python -m uw_scan.worker.scheduler" \
  "$COUNTS UW_SCAN_WORKER_ROLE=ai UW_SCAN_WORKER_INDEX=1 UW_SCAN_WORKER_COUNT=2 uv run python -m uw_scan.worker.scheduler"
