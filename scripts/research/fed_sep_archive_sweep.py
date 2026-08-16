"""Sweep every discoverable official SEP release and record the semantic parse.

This is the committed reproduce path for the Task 4 headline ("the semantic
parser reads 1 of 25 archive releases before the fix, 25 of 25 after").  A
number quoted from an uncommitted throwaway run is not reproducible, so the
sweep writes its full per-release trace -- not just the headline count -- to a
durable JSON artifact.

The sweep fetches the live federalreserve.gov archive.  It makes no UW, IB, or
database calls, and it never writes to Postgres: this is an evidence-layer
diagnostic, not an ingest path.

Reproduce:

    uv run python scripts/research/fed_sep_archive_sweep.py \
        --years 2020-2026 \
        --out docs/research/2026-08-12-fomc-sep-source-probe/sep-archive-sweep.json
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from uw_scan.sources.fed_sep import parse_sep_release
from uw_scan.sources.fed_sep_provider import FedSepProvider

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReleaseOutcome:
    release_key: str
    meeting_date: str
    acquired: bool
    parsed: bool
    horizons: tuple[str, ...] = ()
    projection_count: int = 0
    policy_horizon_count: int = 0
    published_at: str | None = None
    declared_timezone: str | None = None
    calendar_timezone: str | None = None
    prose_total_declared: bool = False
    error_type: str | None = None
    error_message: str | None = None

    def as_json(self) -> dict[str, Any]:
        return {
            "release_key": self.release_key,
            "meeting_date": self.meeting_date,
            "acquired": self.acquired,
            "parsed": self.parsed,
            "horizons": list(self.horizons),
            "projection_count": self.projection_count,
            "policy_horizon_count": self.policy_horizon_count,
            "published_at": self.published_at,
            "declared_timezone": self.declared_timezone,
            "calendar_timezone": self.calendar_timezone,
            "prose_total_declared": self.prose_total_declared,
            "error_type": self.error_type,
            "error_message": self.error_message,
        }


def _parse_years(raw: str) -> tuple[int, ...]:
    if "-" in raw:
        first, last = raw.split("-", 1)
        return tuple(range(int(first), int(last) + 1))
    return tuple(int(part) for part in raw.split(","))


def sweep(years: tuple[int, ...]) -> list[ReleaseOutcome]:
    outcomes: list[ReleaseOutcome] = []
    with FedSepProvider() as provider:
        fetched = provider.fetch_outcomes(years=years)
    for outcome in fetched:
        key = outcome.candidate.release_key
        meeting = outcome.candidate.event_date.isoformat()
        if outcome.bundle is None:
            outcomes.append(
                ReleaseOutcome(
                    release_key=key,
                    meeting_date=meeting,
                    acquired=False,
                    parsed=False,
                    error_type=outcome.error_type,
                    error_message=outcome.error_message,
                )
            )
            continue
        try:
            release = parse_sep_release(outcome.bundle)
        except Exception as exc:
            logger.debug("SEP semantic parse failed for %s: %s", key, repr(exc))
            outcomes.append(
                ReleaseOutcome(
                    release_key=key,
                    meeting_date=meeting,
                    acquired=True,
                    parsed=False,
                    error_type=type(exc).__name__,
                    error_message=str(exc)[:500],
                )
            )
            continue
        policy_horizons = tuple(
            item.horizon
            for item in release.projections
            if item.variable == "federal_funds_rate"
        )
        outcomes.append(
            ReleaseOutcome(
                release_key=key,
                meeting_date=meeting,
                acquired=True,
                parsed=True,
                horizons=policy_horizons,
                projection_count=len(release.projections),
                policy_horizon_count=len(policy_horizons),
                published_at=release.published_at.isoformat(),
                declared_timezone=release.declared_timezone,
                calendar_timezone=release.calendar_timezone,
                prose_total_declared=release.prose_total_declared,
            )
        )
    return outcomes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--years", default="2020-2026")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    years = _parse_years(args.years)
    swept_at = datetime.now(UTC)
    outcomes = sweep(years)

    parsed = [item for item in outcomes if item.parsed]
    acquired = [item for item in outcomes if item.acquired]
    payload = {
        "swept_at": swept_at.isoformat(),
        "years": list(years),
        "release_count": len(outcomes),
        "acquired_count": len(acquired),
        "parsed_count": len(parsed),
        "reproduce": (
            "uv run python scripts/research/fed_sep_archive_sweep.py "
            f"--years {args.years} --out {args.out}"
        ),
        "releases": [item.as_json() for item in outcomes],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

    logger.info(
        "SEP archive sweep %s: %d releases, %d acquired, %d parsed -> %s",
        args.years,
        len(outcomes),
        len(acquired),
        len(parsed),
        args.out,
    )
    for item in outcomes:
        if not item.parsed:
            logger.info(
                "  UNPARSED %s (%s): %s %s",
                item.release_key,
                item.meeting_date,
                item.error_type,
                item.error_message,
            )
    return 0 if len(parsed) == len(outcomes) else 1


if __name__ == "__main__":
    raise SystemExit(main())
