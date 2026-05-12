# Storage migrations

Migrations are plain `.sql` files applied lexically by `scripts/migrate.sh`,
which loops over the files and passes their contents to
`Repository.apply_migration(sql_text)` — a thin wrapper around `cursor.execute()`.

There is no `schema_migrations` tracking table. Every file MUST be idempotent:
use `CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`,
`ALTER TABLE ... ADD COLUMN IF NOT EXISTS`, `ON CONFLICT DO NOTHING` for seeds.
Re-running the runner on an already-migrated DB must be a no-op.

Each file starts with `SET search_path TO uw_scan, public;` so unqualified table
names land in the project schema.
