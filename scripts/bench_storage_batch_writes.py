#!/usr/bin/env python3
"""Measure storage batch-write plumbing without requiring application secrets."""

from __future__ import annotations

import argparse
import os
import statistics
import time
from collections.abc import Iterable


def _build_params(rows: int) -> list[tuple[int, str, int]]:
    return [(idx, f"ticker-{idx % 25}", idx * 10) for idx in range(rows)]


def _time_call(fn, *, repeats: int) -> list[float]:
    durations: list[float] = []
    for _ in range(repeats):
        start = time.perf_counter()
        fn()
        durations.append(time.perf_counter() - start)
    return durations


def _print_result(label: str, rows: int, durations: Iterable[float]) -> None:
    samples = list(durations)
    best = min(samples)
    median = statistics.median(samples)
    rows_per_second = rows / median if median else float("inf")
    print(
        f"{label}: rows={rows} best={best:.6f}s median={median:.6f}s "
        f"rows_per_sec={rows_per_second:.0f}"
    )


def _run_params_only(rows: int, repeats: int) -> None:
    durations = _time_call(lambda: _build_params(rows), repeats=repeats)
    _print_result("params-only tuple build", rows, durations)


def _run_live_postgres(rows: int, repeats: int, legacy_only: bool) -> None:
    database_url = os.environ.get("UW_SCAN_DATABASE_URL")
    if not database_url:
        raise SystemExit(
            "UW_SCAN_DATABASE_URL is required for --mode live-postgres; "
            "use --mode params-only when a disposable DB is unavailable."
        )

    import psycopg

    params = _build_params(rows)
    create_sql = (
        "CREATE TEMP TABLE bench_storage_batch_writes ("
        "id integer PRIMARY KEY, ticker text NOT NULL, amount integer NOT NULL"
        ") ON COMMIT PRESERVE ROWS"
    )
    insert_sql = (
        "INSERT INTO bench_storage_batch_writes (id, ticker, amount) "
        "VALUES (%s, %s, %s) "
        "ON CONFLICT (id) DO UPDATE SET "
        "ticker=EXCLUDED.ticker, amount=EXCLUDED.amount"
    )

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS bench_storage_batch_writes")
            cur.execute(create_sql)
        conn.commit()

        def clear_table() -> None:
            with conn.cursor() as cur:
                cur.execute("TRUNCATE bench_storage_batch_writes")
            conn.commit()

        def run_single_row_executes() -> None:
            clear_table()
            with conn.cursor() as cur:
                for row in params:
                    cur.execute(insert_sql, row)
            conn.commit()

        legacy_durations = _time_call(run_single_row_executes, repeats=repeats)
        _print_result("live-postgres per-row execute", rows, legacy_durations)

        if legacy_only:
            return

        def run_executemany() -> None:
            clear_table()
            with conn.cursor() as cur:
                cur.executemany(insert_sql, params)
            conn.commit()

        batch_durations = _time_call(run_executemany, repeats=repeats)
        _print_result("live-postgres executemany", rows, batch_durations)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["params-only", "live-postgres"], required=True)
    parser.add_argument("--rows", type=int, default=10_000)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument(
        "--legacy-only",
        action="store_true",
        help="Only measure the single-row execute path for pre-change baselines.",
    )
    args = parser.parse_args()

    if args.rows <= 0:
        raise SystemExit("--rows must be positive")
    if args.repeats <= 0:
        raise SystemExit("--repeats must be positive")
    if args.legacy_only and args.mode != "live-postgres":
        raise SystemExit("--legacy-only is only valid with --mode live-postgres")

    if args.mode == "params-only":
        _run_params_only(args.rows, args.repeats)
    else:
        _run_live_postgres(args.rows, args.repeats, args.legacy_only)


if __name__ == "__main__":
    main()
