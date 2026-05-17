# src/uw_scan/storage — Postgres persistence

## Files

- `repository.py` — assembled `Repository` class. Composes per-domain mixins (see "Mixin pattern" below). Methods not yet extracted live directly on `Repository`; PR-2/PR-3 will move the rest.
- `_base.py` — `_BaseMixin` (Repository `__init__` + `conn` property). MUST be LAST in MRO.
- `_helpers.py` — pure utility functions (`_d`, `_nullable_int/float`, `provider_day_bounds`, `redact_params`, `status_family_for`).
- `rows.py` — frozen `@dataclass` row types + `WatchlistCardRow`.
- `audit.py` / `flow.py` / `health.py` / `jobs.py` / `market_data.py` / `scan_outputs.py` — per-domain mixins extracted in PR-1.
- `provider_usage.py` — `ExternalApiRequestRecorder` (out-of-band telemetry writer). Not part of `Repository`.
- `migrations/*.sql` — applied lexically by `scripts/migrate.sh`

## Mixin pattern (post-2026-05-16 PR-1 split)

`Repository` is the assembled class:

```python
class Repository(
    _AuditMixin, _FlowMixin, _HealthMixin, _JobsMixin,
    _MarketDataMixin, _ScanOutputsMixin,
    _BaseMixin,  # MUST be last — owns __init__ and the conn property
):
    # PR-2/PR-3 will move the remaining methods to per-domain mixins.
    # New methods go in the appropriate mixin file, NOT here.
    ...
```

Conventions for the mixin pattern:

- **One mixin class per file.** Naming: `_<Domain>Mixin` in `<domain>.py`.
- **`from __future__ import annotations`** at top of every storage file.
- **No `__init__` on domain mixins.** Only `_BaseMixin` defines it; Python's MRO calls only the leftmost class's `__init__`, so any other mixin defining one would break construction.
- **Type hints for `self._conn` and `self._schema`** as class-level annotations (`_conn: psycopg.Connection`). Values are set by `_BaseMixin.__init__` at runtime.
- **Adding a new domain** → new file `<domain>.py` + `_<Domain>Mixin` class + add to `repository.py`'s import block and inheritance list (above `_BaseMixin`).
- **Adding a new row dataclass** → goes in `rows.py`; re-export from `repository.py`'s `from .rows import (...)` block and `__all__`.
- **Adding a new pure helper** → goes in `_helpers.py`; if externally importable, also re-export from `repository.py`.
- **Backward compat**: callers' `from uw_scan.storage.repository import X` paths MUST keep working — all moved names are explicitly re-exported.

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
