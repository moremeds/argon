"""Resumable NY Fed SME (dealer survey) history backfill through the real job.

The nightly job takes the newest survey and nothing else, so the desk holds one
release and cannot show how dealer expectations MOVED between surveys.  The
history was never unreachable -- the publisher's landing page has always listed
every survey it still hosts -- it was simply never asked for.

Why this is not folded into ``macro_policy_history.py``: that script resumes off
``macro_release_ingest_status``, and the dealer survey deliberately carries
``release_type=None`` because it is not an FOMC release and does not belong in
that catalog.  Its ledger is therefore ``macro_observations``.

Deliberately NOT the artifact table: bytes on disk are not a reading.  The first
run of this script stored all 12 artifacts while 6 of them parsed to nothing, so
an artifact-keyed resume would have reported the history complete and skipped
every survey it had actually failed to read.

The survey is published on the FOMC cycle (~8x/year), NOT weekly or monthly, so
the comparison a reader wants is "previous survey", never "one week ago" -- there
are months with no survey at all.

Reproduce::

    uv run python scripts/backfill/macro_sme_history.py --resume
    uv run python scripts/backfill/macro_sme_history.py --verify
"""

from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Sequence
from datetime import UTC, date, datetime

import psycopg

from uw_scan.config import Settings
from uw_scan.sources.nyfed_sme import NyFedSmeProvider
from uw_scan.worker.jobs.macro_policy_jobs import macro_sme_ingest_job

logger = logging.getLogger("macro_sme_history")

SOURCE = "new_york_fed_sme"


def available_survey_months() -> tuple[date, ...]:
    """Every survey month the publisher currently lists, oldest first."""
    with NyFedSmeProvider() as provider:
        return provider.list_survey_months()


def ingested_survey_months(conn: psycopg.Connection, *, schema: str) -> set[date]:
    """Survey months that produced at least one OBSERVATION.

    Keyed on facts, not artifacts.  A survey whose bytes downloaded but whose
    parse raised has an artifact and no reading; counting it as ingested is how a
    backfill reports success over the exact releases it could not read.
    """
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT DISTINCT release_key FROM {schema}.macro_observations"
            " WHERE source = %s AND release_key LIKE %s",
            (SOURCE, "nyfed-sme:%:xlsx"),
        )
        rows = [row[0] for row in cur.fetchall()]
    months: set[date] = set()
    for record_id in rows:
        stamp = record_id.split(":")[1]
        months.add(date(int(stamp[:4]), int(stamp[5:7]), 1))
    return months


def months_to_run(
    available: Sequence[date], ingested: set[date], *, resume: bool
) -> tuple[date, ...]:
    if not resume:
        return tuple(available)
    return tuple(month for month in available if month not in ingested)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--resume",
        action="store_true",
        help="skip survey months that already produced observations",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="report holdings vs the publisher without fetching any survey",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="ingest at most N surveys this run (oldest first)",
    )
    args = parser.parse_args()

    settings = Settings.from_env()
    dsn = settings.db_dsn()
    conn = psycopg.connect(dsn)
    try:
        available = available_survey_months()
        held = ingested_survey_months(conn, schema=settings.db_schema)
        missing = [month for month in available if month not in held]

        if args.verify:
            logger.info(
                json.dumps(
                    {
                        "published": [f"{m:%Y-%m}" for m in available],
                        "ingested": sorted(f"{m:%Y-%m}" for m in held),
                        "missing": [f"{m:%Y-%m}" for m in missing],
                    },
                    indent=2,
                )
            )
            return 1 if missing else 0

        pending = months_to_run(available, held, resume=args.resume)
        if args.limit is not None:
            pending = pending[: args.limit]
        logger.info(
            "publisher lists %s survey(s); %s already held; running %s",
            len(available),
            len(held),
            [f"{m:%Y-%m}" for m in pending],
        )

        failures: list[str] = []
        for month in pending:
            # One month per call: fetch_bundles fails closed on a month the
            # publisher does not list, so a batch would let one bad survey erase
            # every other release in the same run.
            result = macro_sme_ingest_job(
                dsn=dsn, survey_month=month, observed_at=datetime.now(UTC)
            )
            logger.info(
                "%s: %s (%s/%s releases, obs=%s, failed=%s)",
                f"{month:%Y-%m}",
                result.status,
                result.releases_succeeded,
                result.releases_discovered,
                result.observations_seen,
                list(result.failed_release_keys),
            )
            if result.releases_succeeded < 1:
                failures.append(f"{month:%Y-%m}")

        held_after = ingested_survey_months(conn, schema=settings.db_schema)
        still_missing = [f"{m:%Y-%m}" for m in available if m not in held_after]
        logger.info(
            json.dumps({"failed": failures, "still_missing": still_missing}, indent=2)
        )
        return 1 if failures or still_missing else 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
