"""Refresh option_wizard_local with a recent slice of the mini's option_wizard.

Local dev DBs go stale (11 days, when this was written) and stale data hides
bugs that only appear against real shapes. This pulls the most recent N market
days from the mini so development runs against something realistic.

READ-ONLY against the mini. The source connection is opened in a read-only
transaction and the script never issues a write against it — the mini is the
prodlike writer and nothing here may touch it.

Destination is guarded: the script refuses to run unless the destination is a
local host AND the database name ends in `_local`. That guard is the whole
reason this is a standalone script rather than something wired through
`uw_scan.config` — a typo here would write into the prodlike DB.

Idempotent: each table's synced window is deleted locally and re-copied, so
re-running converges rather than duplicating. Tables without a usable date
column are full-replaced when small and skipped when large.

Credentials come from ~/.pgpass (or PG* env vars) — this script deliberately
takes no password argument so secrets stay out of shell history.

Reproduce:
    uv run python scripts/dev/sync_local_from_mini.py --days 20
    uv run python scripts/dev/sync_local_from_mini.py --days 20 --dry-run
"""

from __future__ import annotations

import argparse
import contextlib
import socket
import subprocess
import sys
import time
from dataclasses import dataclass

import psycopg

SCHEMA = "uw_scan"

# The mini's Postgres requires a password over the network but trusts local
# connections, so we forward a port over SSH and connect through it. The
# credential never leaves the mini and nothing lands in ~/.pgpass here.
SSH_HOST = "macmini"  # ~/.ssh/config: moremeds@100.66.147.98
TUNNEL_PORT = 15432

SRC = {
    "host": "127.0.0.1",
    "port": TUNNEL_PORT,
    "dbname": "option_wizard",
    "user": "argon_app",
}
DST = {
    "host": "127.0.0.1",
    "port": 5432,
    "dbname": "option_wizard_local",
    "user": "chenxi",
    # Startup option, not a SET: a SET inside a transaction is reverted by
    # the per-table rollback, silently re-enabling FK checks mid-run.
    "options": "-c session_replication_role=replica",
}


@contextlib.contextmanager
def ssh_tunnel():
    """Forward the mini's Postgres to TUNNEL_PORT for the life of the sync.

    ExitOnForwardFailure matters: without it ssh reports success while the
    forward silently failed, and the sync would then connect to whatever else
    happens to be on that port.
    """
    # Pre-flight: if something already listens here, ssh fails to bind but the
    # connect-poll below would happily succeed against THAT tunnel — pointing the
    # sync at an unknown database. Refuse instead of silently inheriting it.
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", TUNNEL_PORT)) == 0:
            sys.exit(
                f"port {TUNNEL_PORT} is already in use — a stale tunnel is likely "
                f"still running. Kill it, then re-run:\n"
                f"  lsof -ti :{TUNNEL_PORT} | xargs kill"
            )

    proc = subprocess.Popen(
        [
            "ssh",
            "-N",
            "-o",
            "ExitOnForwardFailure=yes",
            "-o",
            "BatchMode=yes",
            "-L",
            f"{TUNNEL_PORT}:localhost:5432",
            SSH_HOST,
        ]
    )
    try:
        for _ in range(40):  # ~10s for the forward to come up
            if proc.poll() is not None:
                sys.exit(
                    f"ssh tunnel to {SSH_HOST} exited early (rc={proc.returncode})"
                )
            try:
                psycopg.connect(**SRC, connect_timeout=2).close()
                break
            except psycopg.OperationalError:
                time.sleep(0.25)
        else:
            sys.exit(f"ssh tunnel to {SSH_HOST} never became usable")
        yield
    finally:
        proc.terminate()
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=5)


# raw_payloads is 61% of a 30-day slice (5.1 GB of 8.4 GB) and nothing in the
# dashboard reads it — it is the raw UW response archive kept for replay/audit.
# Excluding it by default is the single biggest win in this script.
DEFAULT_EXCLUDE = {"raw_payloads"}

# Preference order matters: market_date is the analytic partition key and gives
# a clean per-day slice, while inserted_at is a write-time fallback that can
# drag in rows whose market_date is far older (backfills). Prefer real business
# dates; fall back to write time only when there is nothing better.
DATE_COL_PREFERENCE = (
    "market_date",
    "date",
    "trade_date",
    "snapshot_date",
    "data_date",
    "as_of",
    "as_of_date",
    "obs_date",
    "curr_date",
    "executed_at",
    "scanned_at",
    "computed_at",
    "created_at",
    "requested_at",
    "fetched_at",
    "started_at",
    "inserted_at",
)

# A dateless table this size is a fact table we cannot slice; copying it whole
# would defeat the point of a windowed sync, so it is skipped and reported.
FULL_COPY_MAX_ROWS = 200_000


@dataclass
class Plan:
    table: str
    date_col: str | None
    est_rows: int


def guard_destination() -> None:
    host = DST["host"]
    name = DST["dbname"]
    if host not in {"127.0.0.1", "localhost", "::1"}:
        sys.exit(f"REFUSING: destination host {host!r} is not local")
    if not name.endswith("_local"):
        sys.exit(f"REFUSING: destination db {name!r} does not end in '_local'")


def tables_with_columns(conn: psycopg.Connection) -> dict[str, set[str]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.relname, a.attname
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
            WHERE n.nspname = %s AND c.relkind = 'r'
            """,
            (SCHEMA,),
        )
        out: dict[str, set[str]] = {}
        for table, col in cur.fetchall():
            out.setdefault(table, set()).add(col)
        return out


def est_rows(conn: psycopg.Connection, table: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COALESCE(c.reltuples, 0)::bigint FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = %s AND c.relname = %s",
            (SCHEMA, table),
        )
        row = cur.fetchone()
        return int(row[0]) if row else 0


def cutoff_date(conn: psycopg.Connection, days: int) -> str:
    """The Nth most recent distinct trading day.

    Counting calendar days would silently under-deliver across holidays, so we
    ask the data which days exist. The source is vol_index_daily rather than
    option_surface_grid_daily: the grid has ~17.8M rows and no index that
    serves DISTINCT, so `SELECT DISTINCT market_date ... LIMIT 20` full-scans
    and sorts it — measured 29.8s for a bare max() and worse for the DISTINCT.
    vol_index_daily carries the same trading calendar in 0.5s and returns an
    identical cutoff.
    """
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT min(d) FROM (SELECT DISTINCT trade_date AS d "
            f"FROM {SCHEMA}.vol_index_daily ORDER BY trade_date DESC LIMIT %s) x",
            (days,),
        )
        row = cur.fetchone()
    if not row or row[0] is None:
        sys.exit("could not determine cutoff: vol_index_daily is empty on the source")
    return row[0].isoformat()


def build_plans(src_cols, dst_cols, exclude: set[str]) -> tuple[list[Plan], list[str]]:
    plans: list[Plan] = []
    skipped: list[str] = []
    shared = sorted(set(src_cols) & set(dst_cols))
    for table in shared:
        if table in exclude:
            skipped.append(f"{table} (excluded)")
            continue
        cols = src_cols[table] & dst_cols[table]
        date_col = next((c for c in DATE_COL_PREFERENCE if c in cols), None)
        plans.append(Plan(table=table, date_col=date_col, est_rows=0))
    only_src = sorted(set(src_cols) - set(dst_cols))
    only_dst = sorted(set(dst_cols) - set(src_cols))
    for t in only_src:
        skipped.append(f"{t} (source only — local schema is behind)")
    for t in only_dst:
        skipped.append(f"{t} (local only — not on the mini yet)")
    return plans, skipped


def sync_table(
    src: psycopg.Connection,
    dst: psycopg.Connection,
    plan: Plan,
    cutoff: str,
    src_cols,
    dst_cols,
) -> tuple[int, str]:
    """Copy one table's window. Returns (rows, mode)."""
    # Only columns present on BOTH sides, so a schema drift in either direction
    # degrades to a narrower copy instead of blowing up mid-transfer.
    cols = sorted(src_cols[plan.table] & dst_cols[plan.table])
    collist = ", ".join(f'"{c}"' for c in cols)

    if plan.date_col:
        where = f'WHERE "{plan.date_col}" >= %(cutoff)s'
        mode = f"window({plan.date_col})"
    else:
        n = est_rows(src, plan.table)
        if n > FULL_COPY_MAX_ROWS:
            return (0, f"SKIPPED (no date column, ~{n:,} rows)")
        where = ""
        mode = "full"

    # Stage into a temp table, then INSERT ... ON CONFLICT DO NOTHING.
    #
    # Copying straight into the target looks cheaper but is wrong: tables with a
    # surrogate `id` primary key (backtest_sweep_results, jobs, scan_runs) hold
    # LOCAL rows whose ids collide with the mini's, and the window-DELETE cannot
    # clear them because they sit outside the window. That is a UniqueViolation
    # mid-COPY, which then aborts the shared source transaction and takes every
    # remaining table down with it. Staging costs one extra local write and makes
    # the whole run insensitive to id collisions.
    tmp = f"sync_stage_{plan.table}"[:63]
    src_sql = f"COPY (SELECT {collist} FROM {SCHEMA}.{plan.table} {where}) TO STDOUT (FORMAT binary)"

    with dst.cursor() as dcur:
        dcur.execute(f'DROP TABLE IF EXISTS pg_temp."{tmp}"')
        # `AS SELECT ... WITH NO DATA` clones the column types without dragging
        # NOT NULL/defaults across — a staging table must accept exactly the
        # subset of columns we copy, nothing more.
        dcur.execute(
            f'CREATE TEMP TABLE "{tmp}" AS '
            f"SELECT {collist} FROM {SCHEMA}.{plan.table} WITH NO DATA"
        )

    with src.cursor() as scur, dst.cursor() as dcur:
        with scur.copy(
            src_sql, {"cutoff": cutoff} if plan.date_col else None
        ) as reader:
            with dcur.copy(
                f'COPY "{tmp}" ({collist}) FROM STDIN (FORMAT binary)'
            ) as writer:
                for block in reader:
                    writer.write(block)

    with dst.cursor() as dcur:
        if plan.date_col:
            dcur.execute(
                f'DELETE FROM {SCHEMA}.{plan.table} WHERE "{plan.date_col}" >= %s',
                (cutoff,),
            )
        else:
            dcur.execute(f"DELETE FROM {SCHEMA}.{plan.table}")
        dcur.execute(
            f"INSERT INTO {SCHEMA}.{plan.table} ({collist}) "
            f'SELECT {collist} FROM "{tmp}" ON CONFLICT DO NOTHING'
        )
        rows = dcur.rowcount if dcur.rowcount and dcur.rowcount > 0 else 0
        dcur.execute(f'DROP TABLE IF EXISTS pg_temp."{tmp}"')
    return (rows, mode)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--days", type=int, default=20, help="most recent N market days (default 20)"
    )
    ap.add_argument(
        "--dry-run", action="store_true", help="print the plan, copy nothing"
    )
    ap.add_argument("--tables", default="", help="comma-separated subset")
    ap.add_argument(
        "--include-raw-payloads",
        action="store_true",
        help="do not exclude raw_payloads",
    )
    args = ap.parse_args()

    guard_destination()
    exclude = set() if args.include_raw_payloads else set(DEFAULT_EXCLUDE)

    print(
        f"source: {SRC['user']}@{SSH_HOST}/{SRC['dbname']} via ssh tunnel (read-only)"
    )
    print(f"dest:   {DST['user']}@{DST['host']}/{DST['dbname']}")

    with ssh_tunnel(), psycopg.connect(**SRC) as src, psycopg.connect(**DST) as dst:
        src.read_only = True  # belt-and-braces: the mini must never be written
        cutoff = cutoff_date(src, args.days)
        print(f"cutoff: {cutoff}  ({args.days} most recent market days)\n")

        src_cols = tables_with_columns(src)
        dst_cols = tables_with_columns(dst)
        plans, skipped = build_plans(src_cols, dst_cols, exclude)
        if args.tables:
            wanted = {t.strip() for t in args.tables.split(",") if t.strip()}
            plans = [p for p in plans if p.table in wanted]

        if args.dry_run:
            for p in plans:
                print(f"  {p.table:<40} {p.date_col or '(no date column)'}")
            for s in skipped:
                print(f"  SKIP {s}")
            return 0

        total = 0
        for p in plans:
            t0 = time.time()
            try:
                rows, mode = sync_table(src, dst, p, cutoff, src_cols, dst_cols)
            except Exception as exc:  # noqa: BLE001 — one bad table must not abort the sync
                dst.rollback()
                src.rollback()  # the failed COPY aborted the SOURCE txn too;
                # without this, every remaining table dies with InFailedSqlTransaction
                print(f"  {p.table:<40} FAILED: {exc!r}")
                continue
            dst.commit()
            total += rows
            print(f"  {p.table:<40} {rows:>10,}  {mode}  {time.time() - t0:.1f}s")

        print(f"\ndone: {total:,} rows")
        for s in skipped:
            print(f"  skipped: {s}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
