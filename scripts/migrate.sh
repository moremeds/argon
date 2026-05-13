#!/usr/bin/env bash
# scripts/migrate.sh — apply all SQL migrations under src/uw_scan/storage/migrations/
# in lexical order against the configured Postgres. Idempotent: every migration uses
# IF NOT EXISTS / ON CONFLICT, so re-running is a no-op.
#
# Honors UW_SCAN_DB_NAME / UW_SCAN_DB_HOST / UW_SCAN_DB_PORT etc. through Settings.
set -euo pipefail

cd "$(dirname "$0")/.."

DSN=$(uv run python -c 'from uw_scan.config import Settings; print(Settings.from_env().db_dsn())')

for f in src/uw_scan/storage/migrations/*.sql; do
  echo "Applying $f..."
  psql "$DSN" -v ON_ERROR_STOP=1 -f "$f"
done

echo "All migrations applied."
