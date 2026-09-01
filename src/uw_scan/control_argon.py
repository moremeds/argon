#!/usr/bin/env python3
"""control-argon — one entry point for verifying and controlling the local stack.

Replaces: scripts/smoke_container_assets.sh, reading scripts/dev.sh by eye, the
`.env.local`-points-at-the-mini browse hack, ad-hoc /tmp Playwright scripts, and
the `## Daily commands` block in CLAUDE.md.

    uv run control-argon doctor
    uv run control-argon sync --days 7
    uv run control-argon smoke AAPL
    uv run control-argon screenshot watchlist --path /

Design notes: docs/superpowers/specs/2026-09-01-control-argon-design.md.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import psycopg

from uw_scan.config import Settings, _enforce_db_isolation
from uw_scan.control_stack import (
    WORKER_LAG_MAX,
    argon_procs,
    cmd_down,
    cmd_up,
    probe,
    read_stack,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCREENSHOT_DIR = REPO_ROOT / "output" / "playwright"

# The mini is the sync source: always on, freshest data. Direct over Tailscale —
# its Postgres answers the same argon_app credentials the MacBook uses, so no ssh.
MINI_HOST = "100.66.147.98"
MINI_DB = "option_wizard"
LOCAL_DB = "option_wizard_local"

# Tables the sync never copies. Deny-list rather than allow-list on purpose: a
# newly added table then syncs BY DEFAULT, so forgetting to update this file
# makes the sync slower (visible) instead of silently incomplete (invisible).
# Everything here is either raw vendor bodies or an audit trail — big, and worth
# nothing on a browse box.
DENY = frozenset(
    {
        "raw_payloads",
        "option_contract_snapshots",
        "external_api_requests",
        "api_request_audit",
        "uw_fetch_memo",
    }
)

# Preferred date column, most-business-meaningful first. `inserted_at` and
# friends are last: they date the WRITE, not the observation, so a backfilled row
# looks fresh (see reference_freshness_from_available_at_is_blind_to_backfill).
DATE_COL_PRIORITY = (
    "market_date",
    "trade_date",
    "data_date",
    "snapshot_date",
    "obs_date",
    "as_of",
    "as_of_date",
    "date",
    "curr_date",
    "period_end",
    "occurred_at",
    "executed_at",
    "scanned_at",
    "computed_at",
    "started_at",
    "requested_at",
    "created_at",
    "captured_at",
    "recorded_at",
    "fetched_at",
    "inserted_at",
    "updated_at",
)

# Under this, copy the whole table: it is a dimension/lookup, and windowing one
# by date yields a useless fragment (or nothing at all, for monthly series).
FULL_COPY_MAX_BYTES = 64 * 1024 * 1024

# What `doctor` calls stale, and after how many days.
FRESHNESS_TABLES = {
    "option_surface_grid_daily": 4,
    "daily_ohlc": 4,
    "watchlist_card": 2,
    "technical_daily": 4,
    "vrp_daily": 5,
    "cri_snapshots": 4,
    "vcg_snapshots": 4,
}

DATE_TYPES = frozenset(
    {"date", "timestamp with time zone", "timestamp without time zone"}
)

OK, WARN, FAIL = "ok  ", "WARN", "FAIL"


def emit(status: str, msg: str) -> None:
    print(f"[{status}] {msg}")


# --------------------------------------------------------------------------
# connections
# --------------------------------------------------------------------------


def local_settings() -> Settings:
    """Local target. `from_env` runs the (host, db_name) tripwire for us."""
    return Settings.from_env()


def mini_dsn(local: Settings) -> str:
    """Source DSN for the mini, guarded by the app's own isolation rules.

    The tripwire in uw_scan.config is a Python import-time guard reached only via
    Settings.from_env — a psql/psycopg connection built by hand never touches it.
    Calling it explicitly is what keeps this command inside the same policy.
    """
    _enforce_db_isolation(MINI_HOST, MINI_DB)
    pw = local.db_password.get_secret_value()
    password_clause = f" password={pw}" if pw else ""
    return (
        f"host={MINI_HOST} port=5432 dbname={MINI_DB} "
        f"user={local.db_user}{password_clause}"
    )


def require_sync_direction(local: Settings) -> None:
    """Refuse anything but mini/option_wizard -> this box/option_wizard_local."""
    if local.db_host == MINI_HOST:
        raise SystemExit(
            "refusing to sync: this box is pointed at the mini "
            f"(UW_SCAN_DB_HOST={local.db_host}). Drop the .env.local override — "
            "syncing the mini onto itself is what this command exists to retire."
        )
    if local.db_name != LOCAL_DB:
        raise SystemExit(
            f"refusing to sync: target db is {local.db_name!r}, expected {LOCAL_DB!r}. "
            "option_wizard_test is TRUNCATEd per test — synced data would not "
            "survive one case; option_wizard is the mini's own prodlike tier."
        )


# --------------------------------------------------------------------------
# schema introspection
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Table:
    name: str
    columns: tuple[str, ...]
    date_columns: tuple[str, ...]
    size_bytes: int
    # GENERATED ALWAYS AS (…) STORED — Postgres rejects an explicit value, so
    # these are dropped from the copy and recomputed on insert. 53 of them.
    generated: frozenset[str] = frozenset()
    # GENERATED ALWAYS AS IDENTITY — an explicit value needs OVERRIDING SYSTEM
    # VALUE. Kept rather than dropped: it is the id ON CONFLICT dedups on.
    identity_always: frozenset[str] = frozenset()

    def date_column(self) -> str | None:
        for candidate in DATE_COL_PRIORITY:
            if candidate in self.date_columns:
                return candidate
        return self.date_columns[0] if self.date_columns else None


def read_schema(conn: psycopg.Connection, schema: str) -> dict[str, Table]:
    rows = conn.execute(
        """
        SELECT c.relname,
               a.attname,
               format_type(a.atttypid, NULL) AS coltype,
               pg_total_relation_size(c.oid) AS sz,
               a.attgenerated,
               a.attidentity
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = %s
        JOIN pg_attribute a ON a.attrelid = c.oid
                           AND a.attnum > 0 AND NOT a.attisdropped
        WHERE c.relkind = 'r'
        ORDER BY c.relname, a.attnum
        """,
        (schema,),
    ).fetchall()
    cols: dict[str, list[str]] = {}
    dates: dict[str, list[str]] = {}
    sizes: dict[str, int] = {}
    gen: dict[str, set[str]] = {}
    ident: dict[str, set[str]] = {}
    for name, col, coltype, size, generated, identity in rows:
        cols.setdefault(name, []).append(col)
        sizes[name] = size
        if coltype in DATE_TYPES:
            dates.setdefault(name, []).append(col)
        if generated:
            gen.setdefault(name, set()).add(col)
        if identity == "a":
            ident.setdefault(name, set()).add(col)
    return {
        name: Table(
            name,
            tuple(c),
            tuple(dates.get(name, ())),
            sizes[name],
            frozenset(gen.get(name, ())),
            frozenset(ident.get(name, ())),
        )
        for name, c in cols.items()
    }


def primary_key_columns(conn: psycopg.Connection, schema: str, table: str) -> list[str]:
    rows = conn.execute(
        """
        SELECT a.attname
        FROM pg_index i
        JOIN pg_class c ON c.oid = i.indrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = %s
        JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = ANY(i.indkey)
        WHERE c.relname = %s AND i.indisprimary
        """,
        (schema, table),
    ).fetchall()
    return [r[0] for r in rows]


# --------------------------------------------------------------------------
# sync
# --------------------------------------------------------------------------


def sync_one(
    src: psycopg.Connection,
    dst: psycopg.Connection,
    schema: str,
    src_table: Table,
    dst_table: Table,
    cutoff: date,
) -> tuple[int, str]:
    """Stream one table's slice mini -> local. Returns (rows, how)."""
    # Column intersection, in the TARGET's order: the two boxes drift apart
    # whenever local is behind on migrations, and a bare COPY would misalign.
    shared = set(src_table.columns)
    cols = [
        c
        for c in dst_table.columns
        if c in shared and c not in dst_table.generated and c not in src_table.generated
    ]
    if not cols:
        return 0, "no shared columns"
    collist = ", ".join(f'"{c}"' for c in cols)

    date_col = src_table.date_column()
    if src_table.size_bytes <= FULL_COPY_MAX_BYTES or date_col is None:
        where, params, how = "", (), "full"
    else:
        where, params, how = f' WHERE "{date_col}" >= %s', (cutoff,), f"≥{cutoff}"

    select = f'SELECT {collist} FROM "{schema}"."{src_table.name}"{where}'

    with dst.cursor() as dcur:
        dcur.execute(
            f"CREATE TEMP TABLE _sync AS SELECT {collist} "
            f'FROM "{schema}"."{dst_table.name}" WITH NO DATA'
        )
        with (
            src.cursor() as scur,
            scur.copy(f"COPY ({select}) TO STDOUT", params) as reader,
        ):
            with dcur.copy(f"COPY _sync ({collist}) FROM STDIN") as writer:
                for block in reader:
                    writer.write(block)
        # Additive, never destructive: no DELETE, so foreign keys that pin rows
        # in place (cited macro evidence, for one) cannot fail the sync, and a
        # re-run is a no-op rather than a churn.
        has_pk = bool(primary_key_columns(dst, schema, dst_table.name))
        conflict = "ON CONFLICT DO NOTHING" if has_pk else ""
        overriding = (
            " OVERRIDING SYSTEM VALUE" if dst_table.identity_always & set(cols) else ""
        )
        dcur.execute(
            f'INSERT INTO "{schema}"."{dst_table.name}" ({collist})'
            f"{overriding} SELECT {collist} FROM _sync {conflict}"
        )
        rows = dcur.rowcount
        dcur.execute("DROP TABLE _sync")
    dst.commit()
    return rows, how


def cmd_sync(args: argparse.Namespace) -> int:
    local = local_settings()
    require_sync_direction(local)
    schema = local.db_schema
    cutoff = (datetime.now(timezone.utc) - timedelta(days=args.days)).date()

    print(
        f"sync  {MINI_HOST}/{MINI_DB} -> {local.db_host}/{local.db_name}  "
        f"(window ≥ {cutoff}, tables ≤ {FULL_COPY_MAX_BYTES // 1024 // 1024} MB copied whole)"
    )

    with (
        psycopg.connect(mini_dsn(local)) as src,
        psycopg.connect(local.db_dsn()) as dst,
    ):
        src_tables = read_schema(src, schema)
        dst_tables = read_schema(dst, schema)

        wanted = sorted((set(src_tables) & set(dst_tables)) - DENY)
        if args.tables:
            requested = {t.strip() for t in args.tables.split(",") if t.strip()}
            unknown = requested - set(wanted)
            if unknown:
                raise SystemExit(f"unknown or denied table(s): {sorted(unknown)}")
            wanted = sorted(requested)

        only_on_mini = sorted(set(src_tables) - set(dst_tables) - DENY)
        if only_on_mini:
            emit(
                WARN,
                f"{len(only_on_mini)} table(s) exist only on the mini "
                f"(run scripts/migrate.sh): {', '.join(only_on_mini[:6])}",
            )

        total = 0
        empty: list[str] = []
        for name in wanted:
            if args.dry_run:
                src_t = src_tables[name]
                how = (
                    "full"
                    if src_t.size_bytes <= FULL_COPY_MAX_BYTES
                    or src_t.date_column() is None
                    else f"≥{cutoff} on {src_t.date_column()}"
                )
                print(f"  {name:<44} {how}")
                continue
            try:
                rows, how = sync_one(
                    src, dst, schema, src_tables[name], dst_tables[name], cutoff
                )
            except psycopg.Error as exc:
                dst.rollback()
                emit(FAIL, f"{name}: {repr(exc)}")
                continue
            total += rows
            if rows == 0 and how != "full":
                empty.append(name)
            print(f"  {name:<44} {rows:>9,} rows  ({how})")

        if not args.dry_run:
            print(f"\n{total:,} rows inserted across {len(wanted)} tables")
            if empty:
                # Self-diagnosing manifest: a windowed table that never yields a
                # row inside the window is almost always slow-moving (monthly
                # macro series) and wants a whole-table copy instead.
                emit(
                    WARN,
                    f"{len(empty)} windowed table(s) copied 0 rows — likely "
                    f"slow-moving, consider raising FULL_COPY_MAX_BYTES or "
                    f"denying them: {', '.join(empty[:8])}",
                )
    return 0


# --------------------------------------------------------------------------
# doctor
# --------------------------------------------------------------------------


def cmd_doctor(args: argparse.Namespace) -> int:
    failures = 0
    local = local_settings()
    # A code default is not deployed state — print what is actually addressed.
    emit(OK, f"db target  {local.db_host}/{local.db_name} schema={local.db_schema}")

    # Same predicate `up` waits on, so the two can never disagree about "ready".
    state = read_stack(args.web_port, args.api_port, REPO_ROOT)
    for name, result, port in (
        ("web", state.web, args.web_port),
        ("api", state.api, args.api_port),
    ):
        if result:
            emit(OK, f"{name:<4}       127.0.0.1:{port} -> 200")
        else:
            failures += 1
            emit(
                FAIL,
                f"{name:<4}       127.0.0.1:{port} -> {result.status or 'unreachable'} "
                f"{result.detail} (start it: uv run control-argon up)",
            )

    if state.api:
        # /api/health answering 200 proves a process is listening, NOT that it is
        # running this checkout's code. A stale uvicorn serves a healthy /health
        # and 500s on every real endpoint — the exact shape of the 2026-08 "three
        # stalled endpoints" incident, which was a whole-stack outage wearing a
        # green health check.
        if state.running_version != state.repo_version:
            failures += 1
            emit(
                FAIL,
                f"api ver    serving {state.running_version}, repo is "
                f"{state.repo_version} — restart: uv run control-argon up --force",
            )
        else:
            emit(OK, f"api ver    {state.running_version}")

        if state.worker_lag is None:
            emit(WARN, "worker     no heartbeat reported")
        elif state.worker_lag > WORKER_LAG_MAX:
            failures += 1
            emit(
                FAIL,
                f"worker     heartbeat {state.worker_lag / 3600:.1f}h old — "
                "no worker is running",
            )
        else:
            emit(OK, f"worker     heartbeat {state.worker_lag:.0f}s old")

        emit(
            OK if state.ws_source else WARN,
            f"ws feed    active_source={state.ws_source or 'none'}",
        )

    # Orphans from other checkouts are the failure this tool exists to make
    # visible: they answer 200 from code that is days old and no longer on disk.
    strays = [
        p
        for p in argon_procs()
        if not p.cwd.startswith(str(REPO_ROOT))
        and {args.web_port, args.api_port} & set(p.ports)
    ]
    for stray in strays:
        emit(
            WARN,
            f"stray      :{','.join(str(x) for x in stray.ports)} held by pid "
            f"{stray.pid} ({stray.role}, {stray.age_human}) from {stray.cwd} — "
            "`control-argon down --all`",
        )

    try:
        conn = psycopg.connect(local.db_dsn(), connect_timeout=5)
    except psycopg.Error as exc:
        emit(FAIL, f"db         unreachable: {repr(exc)}")
        return 1

    with conn:
        tables = read_schema(conn, local.db_schema)
        today = datetime.now(timezone.utc).date()
        stale = False
        for name, max_age in sorted(FRESHNESS_TABLES.items()):
            table = tables.get(name)
            if table is None:
                emit(WARN, f"freshness  {name}: table absent (run scripts/migrate.sh)")
                continue
            col = table.date_column()
            newest = conn.execute(
                f'SELECT max("{col}") FROM "{local.db_schema}"."{name}"'
            ).fetchone()[0]
            if newest is None:
                emit(WARN, f"freshness  {name}: empty — run `control-argon sync`")
                stale = True
                continue
            if isinstance(newest, datetime):
                newest = newest.date()
            age = (today - newest).days
            if age > max_age:
                stale = True
                emit(WARN, f"freshness  {name}: {col}={newest} — stale {age} days")
            else:
                emit(OK, f"freshness  {name}: {col}={newest} ({age}d)")
        if stale:
            emit(WARN, "some tables are stale — run `uv run control-argon sync`")

        # The sync has no manifest to go stale, but it does have a size cutoff.
        # Report what that cutoff currently decides, so the one remaining knob
        # cannot rot silently.
        windowed = [
            t
            for t in tables.values()
            if t.name not in DENY
            and t.size_bytes > FULL_COPY_MAX_BYTES
            and t.date_column() is None
        ]
        if windowed:
            emit(
                WARN,
                "large table(s) with no date column — sync copies them WHOLE: "
                + ", ".join(sorted(t.name for t in windowed)),
            )

    return 1 if failures else 0


# --------------------------------------------------------------------------
# smoke
# --------------------------------------------------------------------------


def cmd_smoke(args: argparse.Namespace) -> int:
    """API enqueue -> DB row -> worker claim -> DB result -> web page renders.

    This is the chain CLAUDE.md describes as ending in "the user validates via
    the web page" — the step that hard-codes a human as the bottleneck.
    """
    ticker = args.ticker.upper()
    api = f"http://127.0.0.1:{args.api_port}"

    health = probe(f"{api}/api/health")
    if not health:
        emit(FAIL, f"api not up at {api} {health.detail} — uv run control-argon up")
        return 1

    req = urllib.request.Request(f"{api}/api/watchlist/{ticker}/rescan", method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            job = json.load(resp)
    except urllib.error.HTTPError as exc:
        emit(FAIL, f"enqueue {ticker}: {repr(exc)} {exc.read()[:200]!r}")
        return 1
    job_id = job["job_id"]
    emit(OK, f"enqueued   job {job_id} for {ticker}")

    deadline = time.monotonic() + args.timeout
    status = job.get("status")
    while time.monotonic() < deadline:
        time.sleep(3)
        state = probe(f"{api}/api/jobs/{job_id}").body
        if state is None:
            continue
        status = state.get("status")
        if status in {"done", "succeeded", "failed", "error"}:
            if status in {"failed", "error"}:
                emit(FAIL, f"worker     job {status}: {state.get('error')}")
                return 1
            emit(OK, f"worker     job {status} (run_id={state.get('run_id')})")
            break
        print(f"  ... {status}", flush=True)
    else:
        emit(
            FAIL,
            f"worker     job still {status!r} after {args.timeout}s — is a "
            "worker running? (control-argon up; APScheduler does not hot-reload)",
        )
        return 1

    page = f"http://127.0.0.1:{args.web_port}/stock/{ticker}"
    rendered = probe(page, timeout=30)
    if not rendered:
        emit(
            FAIL,
            f"web        {page} -> {rendered.status or 'unreachable'} {rendered.detail}",
        )
        return 1
    emit(OK, f"web        {page} -> 200")
    return 0


# --------------------------------------------------------------------------
# screenshot
# --------------------------------------------------------------------------


SHOT_SPEC = """import {{ test }} from "@playwright/test";
test("control-argon screenshot", async ({{ page }}) => {{
  test.setTimeout(90_000);
  await page.setViewportSize({{ width: {width}, height: {height} }});
  await page.goto({path!r});
  await page.waitForLoadState("networkidle").catch(() => {{}});
  await page.waitForTimeout({settle});
  await page.screenshot({{ path: {out!r}, fullPage: {full} }});
}});
"""


def cmd_screenshot(args: argparse.Namespace) -> int:
    """Retires the ad-hoc /tmp Playwright script.

    The output path is fixed under output/playwright/, so a repo-root screenshot
    is structurally impossible rather than merely against CLAUDE.md's rule — a
    rule that had been broken eight times when this was written.
    """
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    out = SCREENSHOT_DIR / f"{Path(args.name).name}.png"
    web = REPO_ROOT / "web"
    spec = web / "tests" / "e2e" / "_control-argon-shot.spec.ts"
    spec.write_text(
        SHOT_SPEC.format(
            width=args.width,
            height=args.height,
            path=args.path,
            settle=args.settle_ms,
            out=str(out),
            full="true" if args.full_page else "false",
        )
    )
    # PW_NO_WEBSERVER is the knob step 1 added when the four extra Playwright
    # configs were deleted: drive a stack that is already running, don't boot one.
    try:
        proc = subprocess.run(
            ["npx", "playwright", "test", "_control-argon-shot", "--reporter=line"],
            cwd=web,
            env={
                **os.environ,
                "PW_NO_WEBSERVER": "1",
                "PLAYWRIGHT_WEB_PORT": str(args.web_port),
            },
            check=False,
        )
    finally:
        spec.unlink(missing_ok=True)
    if proc.returncode != 0 or not out.exists():
        emit(FAIL, f"screenshot failed (is the stack up on :{args.web_port}?)")
        return 1
    emit(OK, f"wrote {out.relative_to(REPO_ROOT)}")
    return 0


# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="control-argon",
        description="Verify and control the local argon stack.",
        epilog=(
            "day-to-day:\n"
            "  uv run control-argon up              start the stack, wait until it serves\n"
            "  uv run control-argon down --all      stop every stale stack\n"
            "  bash scripts/migrate.sh              apply SQL migrations (idempotent)\n"
            "  uv run control-argon doctor          is it up, is it CURRENT, is data fresh\n"
            "  uv run control-argon sync            pull the mini's recent data down\n"
            "  uv run control-argon smoke AAPL      enqueue -> worker -> web, end to end\n"
            "  uv run pytest tests/unit/            fast tests\n"
            "  cd web && npm run test               vitest\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    # Ports live on a shared parent, on the SUBCOMMANDS only. Declaring them on
    # the top-level parser as well looks harmless and is not: the subparser's
    # own default overwrites whatever the pre-subcommand flag set.
    ports = argparse.ArgumentParser(add_help=False)
    ports.add_argument("--web-port", type=int, default=3001)
    ports.add_argument("--api-port", type=int, default=8400)
    sub = p.add_subparsers(dest="command", required=True)

    d = sub.add_parser(
        "doctor", parents=[ports], help="stack liveness, DB tier, data freshness"
    )
    d.set_defaults(func=cmd_doctor)

    u = sub.add_parser(
        "up", parents=[ports], help="start the stack and WAIT until it is serving"
    )
    u.add_argument(
        "--force",
        action="store_true",
        help="stop whatever holds the ports first, including other checkouts",
    )
    u.add_argument("--full", action="store_true", help="DEV_FULL=1 (AI workers)")
    u.add_argument("--timeout", type=int, default=240)
    u.set_defaults(func=cmd_up)

    w = sub.add_parser("down", help="stop this checkout's stack")
    w.add_argument(
        "--all",
        action="store_true",
        help="every argon stack process, any worktree (orphan sweep)",
    )
    w.add_argument(
        "--older-than", type=float, metavar="HOURS", help="only ones this old"
    )
    w.add_argument("--dry-run", action="store_true", help="list, kill nothing")
    w.set_defaults(func=cmd_down)

    s = sub.add_parser("sync", help=f"pull {MINI_DB} from the mini into {LOCAL_DB}")
    s.add_argument("--days", type=int, default=7, help="date window (default 7)")
    s.add_argument("--tables", help="comma-separated subset")
    s.add_argument(
        "--dry-run", action="store_true", help="print the plan, copy nothing"
    )
    s.set_defaults(func=cmd_sync)

    k = sub.add_parser(
        "smoke", parents=[ports], help="API enqueue -> worker -> DB -> web page"
    )
    k.add_argument("ticker")
    k.add_argument("--timeout", type=int, default=180)
    k.set_defaults(func=cmd_smoke)

    shot = sub.add_parser(
        "screenshot", parents=[ports], help="capture a page into output/playwright/"
    )
    shot.add_argument("name", help="output file stem")
    shot.add_argument("--path", default="/", help="app path, e.g. /stock/AAPL")
    shot.add_argument("--width", type=int, default=1440)
    shot.add_argument("--height", type=int, default=1200)
    shot.add_argument("--settle-ms", type=int, default=1500)
    shot.add_argument("--full-page", action="store_true")
    shot.set_defaults(func=cmd_screenshot)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
