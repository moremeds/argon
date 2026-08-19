"""Ingest vintage-bearing macro series as immutable evidence.

Separate from :mod:`uw_scan.worker.jobs.macro_policy_jobs`, which ingests one release at
a time.  A series is not a release: one request returns the whole history, and the thing
that makes it usable for replay is ALFRED's ``realtime_start`` -- the day each value
became the published value.

**The request shape is load-bearing.**  Asking FRED with ``realtime_start = realtime_end
= today`` makes it clamp every returned window to the query window and report today as
the vintage of the 1947 CPI.  That is an artifact of asking, not a fact about publishing,
and it silently destroys the only field this milestone exists to preserve.  So the
request always spans the unbounded vintage window and lets the publisher state each
value's true first-publication day.  Measured and written up in
``scripts/build_inflation_rates_golden_history.py``.

The job computes nothing.  Year-over-year rates, breadth reads and state labels belong
to the engines, which read these rows back through
:mod:`uw_scan.macro.evidence_store`.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

import psycopg

from uw_scan.macro.evidence_store import INFLATION_EVIDENCE, RATES_EVIDENCE
from uw_scan.models.macro import MacroSourceArtifact
from uw_scan.sources.fred import FredProvider
from uw_scan.sources.fred_macro import (
    SERIES_CONTRACT,
    FredSeriesBundle,
    FredSeriesObservation,
    parse_fred_series,
)
from uw_scan.storage.repository import Repository

logger = logging.getLogger(__name__)

FRED_SOURCE = "fred"

#: ALFRED's own sentinels for "every vintage ever". Any narrower window is silently
#: clamped onto the returned rows, so these two values are not tunable knobs.
ALL_VINTAGES_START = date(1776, 7, 4)
ALL_VINTAGES_END = date(9999, 12, 31)

#: FRED refuses a JSON ``series/observations`` request whose real-time window spans more
#: than 2000 vintage dates.  A monthly series mints ~12 vintages a year and never comes
#: close; a daily series mints one on every publication day and blows the cap outright,
#: so the unbounded window above returns HTTP 400 for every daily series.  Bounding the
#: window is the fix, and it is safe: measured against the live API, a bounded request
#: still reports each observation's TRUE first-publication day, not the window edge --
#: ``observation_start=2021-01-01`` returns the 2021-01-01 value stamped
#: ``realtime_start=2021-01-05``.  The clamping the module docstring warns about happens
#: when the window EXCLUDES an observation's real vintage, which is why the daily request
#: starts its observations on the same day it starts its vintages: an observation cannot
#: be published before the day it describes, so nothing returned has a vintage outside
#: the window, and nothing gets clamped.
#:
#: **This date expires.**  The cap is on window WIDTH, not on the start: ~248 vintages a
#: year against a 2000 ceiling is a hard limit of ~8 years, so 2021-01-01 stops working
#: around **January 2029**.  ``test_daily_vintage_start_has_not_expired`` fails a year
#: ahead of that so the deadline arrives as a red build rather than as a dead feed.  To
#: renew, move this date forward -- and know what it costs: it is also the floor on how
#: far back a state can be replayed (the inflation engine reads 18 months, so a
#: 2021-01-01 archive replays to roughly 2022-07), so moving it forward shortens history
#: as well as buying time.
DAILY_VINTAGE_START = date(2021, 1, 1)

#: How far back observations are requested.  Fixed rather than rolling: a start date that
#: moved with the calendar would change the payload bytes every month, mint a new
#: artifact, and make an unchanged history look re-published.
#:
#: Known accrual cost, stated rather than discovered later: every artifact keeps its exact
#: bytes, and a daily series publishes on most weekdays, so each such series mints one new
#: artifact per publication day carrying its whole requested history.  A wider start makes
#: every one of those payloads bigger.  2015 is comfortable for the monthly series and is
#: far more history than the rates engine's 45-day window needs; lower it here (it is a job
#: parameter) if artifact storage becomes the binding constraint.
DEFAULT_OBSERVATION_START = date(2015, 1, 1)

#: Every series the two domain engines read.  Deduplicated because a series may be
#: load-bearing in more than one domain.
DEFAULT_SERIES: tuple[str, ...] = tuple(
    dict.fromkeys(
        contract.series_id for contract in (*INFLATION_EVIDENCE, *RATES_EVIDENCE)
    )
)


@dataclass(frozen=True)
class MacroSeriesIngestResult:
    source: str
    status: str
    series_attempted: int
    series_succeeded: int
    artifacts_seen: int
    observations_created: int
    observations_unchanged: int
    #: Named rather than counted: an operator can re-run a specific series, not "the
    #: two that failed".
    failed_series: tuple[str, ...] = ()
    error_type: str | None = None
    error_message: str | None = None


def macro_fred_series_ingest_job(
    *,
    dsn: str,
    api_key: str,
    series: Sequence[str] = DEFAULT_SERIES,
    observation_start: date = DEFAULT_OBSERVATION_START,
    observed_at: datetime | None = None,
    provider_factory: Callable[[], Any] | None = None,
    max_attempts: int = 3,
    backoff_base_seconds: float = 1.0,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> MacroSeriesIngestResult:
    """Fetch each series' full vintage history and persist it as evidence.

    Each series is fetched, parsed and committed on its own.  One series whose schema
    drifted must not cost the seven that are fine -- the same isolation the policy
    ingest learned after a single unreadable release produced ten artifacts and zero
    facts.
    """
    if not series:
        raise ValueError("macro series ingest requires at least one series")
    seen_at = observed_at or datetime.now(UTC)
    factory = provider_factory or (lambda: FredProvider(api_key=api_key))

    artifacts = 0
    created = 0
    unchanged = 0
    succeeded = 0
    failures: list[tuple[str, tuple[str, str]]] = []

    with psycopg.connect(dsn) as conn:
        repo = Repository(conn)
        for series_id in series:
            try:
                counts = _ingest_series(
                    repo,
                    conn,
                    series_id=series_id,
                    observation_start=observation_start,
                    seen_at=seen_at,
                    provider_factory=factory,
                    max_attempts=max_attempts,
                    backoff_base_seconds=backoff_base_seconds,
                    sleep_fn=sleep_fn,
                )
            except Exception as exc:
                logger.warning(
                    "macro series ingest failed for %s: %s", series_id, repr(exc)
                )
                conn.rollback()
                failures.append((series_id, _error_parts(exc)))
                continue
            artifacts += counts[0]
            created += counts[1]
            unchanged += counts[2]
            succeeded += 1

        if failures:
            first_series, (first_type, first_message) = failures[0]
            error_type: str | None = "MacroSeriesFailures"
            error_message: str | None = (
                f"{len(failures)} of {len(series)} series failed; "
                f"first {first_series}: {first_type}: {first_message}"
            )[:1000]
            repo.upsert_macro_source_status(
                FRED_SOURCE,
                status="degraded",
                attempted_at=seen_at,
                error_type=error_type,
                error_message=error_message,
            )
        else:
            error_type = None
            error_message = None
            repo.upsert_macro_source_status(
                FRED_SOURCE, status="ok", attempted_at=seen_at
            )
        conn.commit()

    return MacroSeriesIngestResult(
        source=FRED_SOURCE,
        status="degraded" if failures else "ok",
        series_attempted=len(series),
        series_succeeded=succeeded,
        artifacts_seen=artifacts,
        observations_created=created,
        observations_unchanged=unchanged,
        failed_series=tuple(series_id for series_id, _ in failures),
        error_type=error_type,
        error_message=error_message,
    )


def _ingest_series(
    repo: Repository,
    conn: psycopg.Connection,
    *,
    series_id: str,
    observation_start: date,
    seen_at: datetime,
    provider_factory: Callable[[], Any],
    max_attempts: int,
    backoff_base_seconds: float,
    sleep_fn: Callable[[float], None],
) -> tuple[int, int, int]:
    raw_bytes, source_url = _fetch_with_retry(
        series_id=series_id,
        observation_start=observation_start,
        provider_factory=provider_factory,
        max_attempts=max_attempts,
        backoff_base_seconds=backoff_base_seconds,
        sleep_fn=sleep_fn,
    )
    bundle = FredSeriesBundle.from_bytes(
        series_id=series_id,
        source_url=source_url,
        raw_bytes=raw_bytes,
        retrieved_at=seen_at,
    )
    observations = parse_fred_series(bundle)

    artifact = bundle.artifact
    artifact_id = repo.insert_macro_artifact(
        source=artifact.source,
        source_kind=artifact.source_kind,
        source_record_id=artifact.source_record_id,
        source_url=artifact.source_url,
        published_at=artifact.published_at,
        available_at=artifact.available_at,
        retrieved_at=artifact.retrieved_at,
        content_hash=artifact.content_hash,
        parser_version=artifact.parser_version,
        quality_status=artifact.quality_status,
        cost_class=artifact.cost_class,
        media_type=artifact.media_type,
        content_length=artifact.content_length,
        vintage_bearing=artifact.vintage_bearing,
        raw_bytes=artifact.raw_bytes,
    )
    outcome = repo.upsert_macro_series_observations(
        [
            _observation_row(observation, artifact_id=artifact_id, artifact=artifact)
            for observation in observations
        ],
        seen_at=seen_at,
    )
    conn.commit()
    return 1, outcome.created, outcome.unchanged


def _observation_row(
    observation: FredSeriesObservation,
    *,
    artifact_id: int,
    artifact: MacroSourceArtifact,
) -> dict[str, Any]:
    contract = SERIES_CONTRACT[observation.series_id]
    return {
        "artifact_id": artifact_id,
        "domain": contract.domain,
        "series_id": observation.series_id,
        "period_end": observation.period_end,
        "frequency": contract.frequency,
        "unit": observation.unit,
        "value_numeric": observation.value_numeric,
        "source": artifact.source,
        "source_record_id": artifact.source_record_id,
        # FRED dates a vintage to the day and states no release time, so there is no
        # publisher instant to record.  ``available_at`` carries the day itself; a
        # fabricated 08:30 ET would read as a precision the publisher never gave.
        "published_at": None,
        "available_at": observation.available_at,
        "parser_version": observation.parser_version,
        "quality_status": "valid",
        "cost_class": artifact.cost_class,
    }


def request_window(series_id: str, observation_start: date) -> tuple[date, date, date]:
    """Return ``(observation_start, realtime_start, realtime_end)`` for one series.

    Split by publication frequency because the publisher's own limit is: monthly series
    get the unbounded vintage window and their full requested history; daily series get
    a bounded one, because the unbounded window exceeds FRED's 2000-vintage ceiling and
    returns nothing at all.

    An unknown series id gets the unbounded window rather than a guess.  It is the
    conservative branch: worst case is the 400 this function exists to avoid, which is
    loud, whereas guessing "daily" would silently truncate a monthly series' history.
    """
    contract = SERIES_CONTRACT.get(series_id)
    if contract is None or contract.frequency != "daily":
        return observation_start, ALL_VINTAGES_START, ALL_VINTAGES_END
    # Observations start where the vintages do, so every row returned carries its real
    # first-publication day.  ``max`` keeps an explicitly narrower caller request narrow.
    return (
        max(observation_start, DAILY_VINTAGE_START),
        DAILY_VINTAGE_START,
        ALL_VINTAGES_END,
    )


def _fetch_with_retry(
    *,
    series_id: str,
    observation_start: date,
    provider_factory: Callable[[], Any],
    max_attempts: int,
    backoff_base_seconds: float,
    sleep_fn: Callable[[float], None],
) -> tuple[bytes, str]:
    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")
    obs_start, realtime_start, realtime_end = request_window(
        series_id, observation_start
    )
    for attempt in range(max_attempts):
        try:
            with provider_factory() as provider:
                return provider.fetch_series_payload(
                    series_id,
                    start=obs_start,
                    realtime_start=realtime_start,
                    realtime_end=realtime_end,
                )
        except Exception:
            if attempt + 1 == max_attempts:
                raise
            sleep_fn(backoff_base_seconds * (2**attempt))
    raise AssertionError("retry loop exhausted without returning or raising")


def _error_parts(exc: Exception) -> tuple[str, str]:
    return f"{type(exc).__module__}.{type(exc).__name__}", str(exc)
