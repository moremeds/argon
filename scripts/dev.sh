#!/usr/bin/env bash
# scripts/dev.sh — run Next.js, FastAPI, and the worker scheduler concurrently.
# Uses npx concurrently from the web/ package so we don't add a top-level node dep.
set -euo pipefail

cd "$(dirname "$0")/.."

# Ensure web/ deps are installed (cheap if already cached).
if [ ! -d web/node_modules ]; then
  ( cd web && npm install )
fi

# Color-prefixed concurrent run. Press Ctrl-C to stop all three.
exec npx --prefix web concurrently \
  -n next,api,worker \
  -c cyan,green,yellow \
  "cd web && npm run dev" \
  "uv run uvicorn uw_scan.api.server:app --host 127.0.0.1 --port 8400 --reload --reload-dir src" \
  "uv run python -m uw_scan.worker.scheduler"
