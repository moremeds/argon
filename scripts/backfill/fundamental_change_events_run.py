"""Run (or preview) the delta-rail change-event derive for one night
(Task 8, spec §5-iv, Task 17's seeding path — no /tmp one-offs).

    uv run python scripts/backfill/fundamental_change_events_run.py \
        --as-of 2026-08-26 [--execute]

Dry-run by default: computes each class's CANDIDATE rows (calling the SAME
private per-class functions `derive_change_events` uses — never a duplicate
copy of the entry/exit/shift/coverage/flip logic) and prints per-class counts
without persisting, so an empty run is VISIBLE as an explicit zero rather
than a silent no-op. Pass `--execute` to actually call
`derive_change_events`, which writes through `ResearchEventsRepository.
record_events` and is idempotent — rerunning the same `--as-of` after an
`--execute` writes zero new rows for every class whose underlying state
hasn't changed (see the module's idempotency note).

The discovery gate must already have registered the five classes as `live`
(`register_discovery_gate` in worker/jobs/research_events_derive.py) before
`--execute` — otherwise `derive_change_events` raises, by design.

`--as-of` IS NOT A UNIFORM REPLAY DATE (fix round 1, I4) — see
`fundamental_change_events.py`'s module docstring for the full explanation.
In short: `implied_move_shift` selects strictly by `as_of` and silently
yields 0 for anything but the newest night on file, while the other four
classes ignore `as_of` for selection and always read the LATEST live state
— so a past `--as-of` with `--execute` would derive TODAY's facts and stamp
them with a BACKDATED `first_known_at`, corrupting the very "when did the
desk know" ledger this job exists to keep honest. `--execute` therefore
REFUSES a non-today `--as-of` unless `--allow-backdate` is passed
explicitly — pass it only when you understand you are choosing to backdate
`first_known_at` on today's facts (e.g. a deliberate historical replay of a
night whose facts genuinely have not changed since).
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date

import psycopg

from uw_scan.config import Settings
from uw_scan.storage.fundamental_scores import FundamentalScoresRepository
from uw_scan.worker.jobs.fundamental_change_events import (
    _band_entry_events,
    _band_exit_events,
    _bucket_flip_events,
    _coverage_change_events,
    _implied_move_shift_events,
    derive_change_events,
)

log = logging.getLogger("fundamental_change_events_run")


def _dry_run_counts(
    conn: psycopg.Connection, *, as_of: date, schema: str
) -> dict[str, int]:
    """Candidate row counts per class, computed via the SAME functions
    `derive_change_events` calls to write — this previews what a real run
    would attempt, not a re-derived estimate."""
    engine_version = FundamentalScoresRepository(conn, schema=schema).active_version()
    counts = {
        "band_entry": 0,
        "band_exit": 0,
        "implied_move_shift": len(
            _implied_move_shift_events(conn, schema=schema, as_of=as_of)
        ),
        "coverage_change": len(
            _coverage_change_events(conn, schema=schema, as_of=as_of)
        ),
        "bucket_flip": 0,
    }
    if engine_version is not None:
        counts["band_entry"] = len(
            _band_entry_events(
                conn, schema=schema, engine_version=engine_version, as_of=as_of
            )
        )
        counts["band_exit"] = len(
            _band_exit_events(
                conn, schema=schema, engine_version=engine_version, as_of=as_of
            )
        )
        counts["bucket_flip"] = len(
            _bucket_flip_events(
                conn, schema=schema, engine_version=engine_version, as_of=as_of
            )
        )
    return counts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--as-of",
        required=True,
        type=date.fromisoformat,
        help=(
            "the night to derive. NOT a uniform replay date: "
            "implied_move_shift selects strictly by this date (silently 0 "
            "once a later night lands), while band_entry/band_exit/"
            "coverage_change/bucket_flip ignore it for selection and always "
            "read the LATEST live state — see the module docstring. A "
            "non-today value with --execute is refused unless "
            "--allow-backdate is also passed."
        ),
    )
    ap.add_argument(
        "--execute",
        action="store_true",
        help="write events (default: dry-run, compute and print candidate counts only)",
    )
    ap.add_argument(
        "--allow-backdate",
        action="store_true",
        help=(
            "required alongside --execute when --as-of is not today's date. "
            "Without it, --execute on a past/future --as-of is refused, "
            "because four of the five classes would derive TODAY's live "
            "state and stamp it with a first_known_at backdated to --as-of."
        ),
    )
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s"
    )

    if args.execute and args.as_of != date.today() and not args.allow_backdate:
        log.error(
            "--execute with --as-of=%s (today is %s) refused: "
            "band_entry/band_exit/coverage_change/bucket_flip do not select "
            "by --as-of and would derive TODAY's facts under a BACKDATED "
            "first_known_at. Pass --allow-backdate to proceed deliberately.",
            args.as_of,
            date.today(),
        )
        return 1

    settings = Settings.from_env()

    with psycopg.connect(settings.db_dsn()) as conn:
        if args.execute:
            result = derive_change_events(
                conn, as_of=args.as_of, schema=settings.db_schema
            )
            mode = "executed"
        else:
            result = _dry_run_counts(conn, as_of=args.as_of, schema=settings.db_schema)
            mode = "dry-run"

    for cls in (
        "band_entry",
        "band_exit",
        "implied_move_shift",
        "coverage_change",
        "bucket_flip",
    ):
        print(f"{cls:20s} {result[cls]:4d}")
    print(f"{mode}: as_of={args.as_of} total={sum(result.values())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
