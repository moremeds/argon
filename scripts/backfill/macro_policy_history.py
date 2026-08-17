"""Resumable 2020+ FOMC statement and SEP backfill through the production jobs.

The daily scheduler runs the current year only; the whole archive is not
re-downloaded every night.  This script fills the history behind it, one year at
a time, by calling the SAME worker entry points — there is no side-channel write
path, so every artifact and observation lands under the same evidence contract
the nightly job uses.

Resumability reads ``macro_release_ingest_status``: a PAST year whose every
discovered release is ``ok`` is skipped without touching the network.  The
current year is never skipped — the Fed has not finished publishing it, so
"complete" cannot be true of it.

Exits non-zero if any release in the requested window is not ``ok``, and if the
window produced no releases at all: a vacuous pass would hide a discovery outage.

Reproduce::

    uv run python scripts/backfill/macro_policy_history.py \\
        --start-year 2020 --end-year 2026 --resume
    uv run python scripts/backfill/macro_policy_history.py --verify
"""

from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import psycopg

from uw_scan.config import Settings
from uw_scan.storage.repository import Repository
from uw_scan.worker.jobs.macro_policy_jobs import (
    macro_fomc_statement_ingest_job,
    macro_sep_ingest_job,
)

logger = logging.getLogger("macro_policy_history")

#: 2020 is where the durable window starts: COVID policy and the 2022 hiking
#: cycle define the regime the desk trades in.
EARLIEST_YEAR = 2020
SOURCES = ("federal_reserve_fomc", "federal_reserve_sep")
#: A year is only "done" when every release in it produced facts. ``discovered``
#: and ``artifact_only`` both mean bytes without a reading.
COMPLETE_STATUS = "ok"


def resolve_years(*, start_year: int, end_year: int) -> tuple[int, ...]:
    if start_year < EARLIEST_YEAR:
        raise ValueError(f"--start-year must be {EARLIEST_YEAR} or later")
    if end_year < start_year:
        raise ValueError("--end-year must not be before --start-year")
    return tuple(range(start_year, end_year + 1))


def years_to_run(
    years: Sequence[int],
    statuses: Sequence[dict[str, Any]],
    *,
    current_year: int,
    resume: bool,
) -> tuple[int, ...]:
    if not resume:
        return tuple(years)
    by_year: dict[int, list[str]] = {}
    for status in statuses:
        event_date = status["event_date"]
        by_year.setdefault(event_date.year, []).append(status["status"])
    return tuple(
        year
        for year in years
        # A year we never attempted has no rows and must run.  A year the Fed is
        # still publishing into can never be proven complete.
        if year >= current_year
        or year not in by_year
        or any(state != COMPLETE_STATUS for state in by_year[year])
    )


def backfill_exit_code(statuses: Sequence[dict[str, Any]]) -> int:
    if not statuses:
        return 1
    return 0 if all(s["status"] == COMPLETE_STATUS for s in statuses) else 1


def _statuses(repo: Repository, years: Sequence[int]) -> list[dict[str, Any]]:
    wanted = set(years)
    return [
        row
        for row in repo.fetch_macro_release_statuses(sources=SOURCES)
        if row["event_date"].year in wanted
    ]


def _report(statuses: Sequence[dict[str, Any]]) -> dict[str, Any]:
    return {
        "releases": len(statuses),
        "ok": sum(1 for s in statuses if s["status"] == COMPLETE_STATUS),
        "not_ok": sorted(
            {
                f"{s['release_key']}={s['status']}"
                for s in statuses
                if s["status"] != COMPLETE_STATUS
            }
        ),
    }


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-year", type=int, default=EARLIEST_YEAR)
    parser.add_argument("--end-year", type=int, default=None)
    parser.add_argument(
        "--resume",
        action="store_true",
        help="skip past years whose every discovered release already ingested",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="audit the catalog without fetching anything",
    )
    args = parser.parse_args()

    observed_at = datetime.now(UTC)
    end_year = args.end_year if args.end_year is not None else observed_at.year
    try:
        years = resolve_years(start_year=args.start_year, end_year=end_year)
    except ValueError as exc:
        parser.error(str(exc))

    settings = Settings.from_env()
    dsn = settings.db_dsn()
    repo = Repository(psycopg.connect(dsn), schema=settings.db_schema)
    try:
        if args.verify:
            statuses = _statuses(repo, years)
            logger.info(json.dumps(_report(statuses), indent=2))
            return backfill_exit_code(statuses)

        pending = years_to_run(
            years,
            _statuses(repo, years),
            current_year=observed_at.year,
            resume=args.resume,
        )
        skipped = [year for year in years if year not in pending]
        if skipped:
            logger.info("resume: already complete, skipping %s", skipped)
        for year in pending:
            for label, job in (
                ("statement", macro_fomc_statement_ingest_job),
                ("sep", macro_sep_ingest_job),
            ):
                result = job(dsn=dsn, years=(year,), observed_at=datetime.now(UTC))
                logger.info(
                    "%s %s: %s (%s/%s releases, failed=%s)",
                    year,
                    label,
                    result.status,
                    result.releases_succeeded,
                    result.releases_discovered,
                    list(result.failed_release_keys),
                )
        statuses = _statuses(repo, years)
        logger.info(json.dumps(_report(statuses), indent=2))
        return backfill_exit_code(statuses)
    finally:
        repo.conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
