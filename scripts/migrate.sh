#!/usr/bin/env bash
# scripts/migrate.sh — apply all SQL migrations under
# src/uw_scan/storage/migrations/ in lexical order against the configured
# Postgres. Idempotent: every migration uses IF NOT EXISTS / ON CONFLICT,
# so re-running is a no-op.
#
# Honors UW_SCAN_DB_NAME / UW_SCAN_DB_HOST / UW_SCAN_DB_PORT etc. through
# Settings. Runs in-process via psycopg (no per-file psql subprocess).
set -euo pipefail

cd "$(dirname "$0")/.."
exec uv run python -m uw_scan.storage.migrate_runner
