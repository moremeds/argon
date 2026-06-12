"""In-process SQL migration runner.

Reads every ``*.sql`` under ``src/uw_scan/storage/migrations/`` in lexical
order and applies it via a single psycopg connection. Replaces the
per-file ``psql`` subprocess loop that ``scripts/migrate.sh`` used to run,
which paid ~30ms × 82 files of fork+connect cost per invocation. The
integration-test conftest now imports ``apply_migrations`` directly so
fixtures pay zero subprocess overhead.

Requires ``conn.autocommit = True`` because at least three migrations
(``026``, ``027``, ``035``) use ``CREATE INDEX CONCURRENTLY`` /
``DROP INDEX CONCURRENTLY``, which PostgreSQL forbids inside an explicit
transaction block. Each statement in a file is sent as its own simple
query so the server doesn't wrap multi-statement batches in an implicit
transaction.

CLI entry point::

    uv run python -m uw_scan.storage.migrate_runner
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

import psycopg

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def discover_migrations(migrations_dir: Path = MIGRATIONS_DIR) -> list[Path]:
    """Return every ``*.sql`` file in ``migrations_dir`` sorted lexically."""
    return sorted(p for p in migrations_dir.glob("*.sql"))


def split_sql_statements(sql: str) -> list[str]:
    """Split a SQL script on top-level ``;`` boundaries.

    Aware of single-quoted strings, double-quoted identifiers,
    ``$tag$``-style dollar quotes (used for ``DO $$ ... $$`` blocks),
    ``-- line`` comments and ``/* block */`` comments. Statements with
    only whitespace/comments are dropped.

    We send each statement separately because psycopg's multi-statement
    ``execute`` wraps the batch in an implicit transaction on the server,
    which ``CREATE INDEX CONCURRENTLY`` rejects.
    """
    statements: list[str] = []
    current: list[str] = []
    i = 0
    n = len(sql)
    state: str | None = None
    dollar_tag = ""

    while i < n:
        c = sql[i]

        if state is None:
            if c == ";":
                stmt = "".join(current).strip()
                if stmt:
                    statements.append(stmt)
                current = []
                i += 1
                continue
            if c == "'":
                state = "sq"
                current.append(c)
                i += 1
                continue
            if c == '"':
                state = "id"
                current.append(c)
                i += 1
                continue
            if c == "-" and i + 1 < n and sql[i + 1] == "-":
                state = "lc"
                current.append(c)
                i += 1
                continue
            if c == "/" and i + 1 < n and sql[i + 1] == "*":
                state = "bc"
                current.append(c)
                current.append(sql[i + 1])
                i += 2
                continue
            if c == "$":
                # Try to consume a dollar-quote tag: $tag$ or $$.
                j = i + 1
                while j < n and (sql[j].isalnum() or sql[j] == "_"):
                    j += 1
                if j < n and sql[j] == "$":
                    dollar_tag = sql[i : j + 1]
                    state = "dq"
                    current.append(dollar_tag)
                    i = j + 1
                    continue
            current.append(c)
            i += 1
            continue

        if state == "sq":
            current.append(c)
            if c == "'":
                # Escaped quote ('') stays inside the string literal.
                if i + 1 < n and sql[i + 1] == "'":
                    current.append(sql[i + 1])
                    i += 2
                    continue
                state = None
            i += 1
            continue

        if state == "id":
            current.append(c)
            if c == '"':
                if i + 1 < n and sql[i + 1] == '"':
                    current.append(sql[i + 1])
                    i += 2
                    continue
                state = None
            i += 1
            continue

        if state == "lc":
            current.append(c)
            if c == "\n":
                state = None
            i += 1
            continue

        if state == "bc":
            current.append(c)
            if c == "*" and i + 1 < n and sql[i + 1] == "/":
                current.append(sql[i + 1])
                i += 2
                state = None
                continue
            i += 1
            continue

        if state == "dq":
            if c == "$" and sql.startswith(dollar_tag, i):
                current.append(dollar_tag)
                i += len(dollar_tag)
                state = None
                dollar_tag = ""
                continue
            current.append(c)
            i += 1
            continue

    tail = "".join(current).strip()
    if tail:
        statements.append(tail)
    return statements


def apply_migrations(
    conn: psycopg.Connection,
    *,
    migrations_dir: Path = MIGRATIONS_DIR,
    log: Callable[[str], None] = print,
) -> None:
    if not conn.autocommit:
        raise RuntimeError(
            "apply_migrations requires conn.autocommit=True "
            "(CONCURRENTLY index ops cannot run inside a transaction)"
        )
    for f in discover_migrations(migrations_dir):
        log(f"Applying {f.name}...")
        for stmt in split_sql_statements(f.read_text()):
            conn.execute(stmt)


def main() -> int:
    from uw_scan.config import Settings

    settings = Settings.from_env()
    with psycopg.connect(settings.db_dsn(), autocommit=True) as conn:
        apply_migrations(conn)
    print("All migrations applied.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
