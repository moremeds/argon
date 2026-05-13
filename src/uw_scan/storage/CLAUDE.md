# src/uw_scan/storage — Postgres persistence

## Files

- `repository.py` — `Repository` class. One method per insert/select. No `**kwargs` splatting from arbitrary dicts.
- `migrations/*.sql` — applied lexically by `scripts/migrate.sh`

## Repository conventions

- **One conn per worker tick / one conn per request.** `scheduler._repo()` and `api/deps.py` are the only places that open connections.
- **`Jsonb(payload)` for jsonb columns** — psycopg won't auto-encode dicts.
- **`Decimal` round-trips natively.** Pass `Decimal`, get `Decimal` back. Don't `float()` at the boundary.
- **No ORM.** Cursor + parameterized SQL. Never f-string a value into a query.
- **Schema is `uw_scan`** — `Repository(conn, schema=...)` sets `search_path` at construction; queries use unqualified names.
- **Advisory locks** — `pg_try_advisory_lock(<key>)` for single-flight backfills and full-scan kickoffs. Release in `finally`.

## Migrations

- Applied by `scripts/migrate.sh` via lexical sort over `migrations/*.sql`
- **No `schema_migrations` table** — every file MUST be idempotent:
  - `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS`
  - `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`
  - `ON CONFLICT DO NOTHING` for seeds
- **Header every file** with `SET search_path TO uw_scan, public;`
- **Re-running on a migrated DB is a no-op.** Test this locally before committing.
- New migration → next lexical number (`015_…`). Don't renumber existing files.

## When the schema changes

1. Write the migration (idempotent)
2. Add the `dataclass` row + `Repository` method
3. Update the assembler in `reports/*`
4. Add `pytest-postgresql` integration test under `tests/integration/storage/`
