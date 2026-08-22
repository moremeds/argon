"""Ingest the rates market layer as immutable evidence.

Sibling of :mod:`uw_scan.worker.jobs.macro_series_ingest`, and it shares that job's two
structural choices: the artifact is written and COMMITTED before anything is parsed out of
it, and each feed is isolated so one publisher's schema change cannot cost the others.

What it does NOT do is read ``rates_treasury_auctions`` or ``rates_cftc_tff_weekly``.  Those
tables key on ``(..., as_of)`` and update on conflict, so a value read back from one may
already have been overwritten; promoting it here would launder a mutated number into a store
whose whole premise is immutability.  The publishers are asked directly, and the legacy
tables stay read models for the existing ``/rates`` surface.

**Window shapes differ by publisher, and neither is a knob.**  CFTC is asked for a bounded
recent window because these bytes are kept forever: the full history since 2015 is 12.5 MB
per fetch against 56 KB for 120 days, and after the first backfill every run past the window
is re-reading history already stored.  TreasuryDirect cannot be windowed at all -- it accepts
``startDate``/``endDate``, ignores them, and returns a fixed 250-row cap -- so the whole
payload is the artifact, and the ``type`` parameter is what selects how far back that cap
reaches.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, TypeAlias

import psycopg

from uw_scan.macro.rates_market import (
    POSITIONING_SOURCE,
    SUPPLY_REQUEST_TYPES,
    SUPPLY_SOURCE,
    MarketObservation,
    observation_row,
    parse_positioning_observations,
    parse_supply_observations,
    positioning_artifact,
    supply_artifact,
)
from uw_scan.models.macro import MacroSourceArtifact
from uw_scan.sources.cftc_tff import CftcTffProvider
from uw_scan.sources.treasury_supply import TreasurySupplyProvider
from uw_scan.storage.repository import Repository

logger = logging.getLogger(__name__)

#: A feed hands back its artifact and a way to parse it LATER.  Deferring the parse is what
#: lets the artifact be committed first: a publisher schema change makes the parser raise,
#: and parsing before the insert would roll back the exact bytes that caused the failure --
#: destroying the evidence on precisely the run where it is needed.
Feed: TypeAlias = Callable[
    [], tuple[MacroSourceArtifact, Callable[[], list[MarketObservation]]]
]

#: How far back the weekly positioning report is requested on a scheduled run.
#:
#: 120 days rather than a rolling year: the longest publication outage measured across 205
#: releases was ten consecutive weeks (the 2025 funding lapse), so this clears the worst
#: observed backlog with room and still keeps one artifact under 60 KB.  Deep history is a
#: one-off backfill's job -- pass ``positioning_start`` explicitly for that.
DEFAULT_POSITIONING_LOOKBACK_DAYS = 120


@dataclass(frozen=True)
class MacroMarketLayerIngestResult:
    status: str
    feeds_attempted: int
    feeds_succeeded: int
    artifacts_seen: int
    observations_created: int
    observations_unchanged: int
    #: Named rather than counted, so an operator can re-run the one that failed.
    failed_feeds: tuple[str, ...] = ()
    error_type: str | None = None
    error_message: str | None = None


def macro_market_layer_ingest_job(
    *,
    dsn: str,
    supply_types: Sequence[str] = SUPPLY_REQUEST_TYPES,
    positioning_start: date | None = None,
    positioning_lookback_days: int = DEFAULT_POSITIONING_LOOKBACK_DAYS,
    observed_at: datetime | None = None,
    supply_provider_factory: Callable[[], Any] | None = None,
    positioning_provider_factory: Callable[[], Any] | None = None,
    max_attempts: int = 3,
    backoff_base_seconds: float = 1.0,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> MacroMarketLayerIngestResult:
    """Fetch supply and positioning from their publishers and persist them as evidence."""
    seen_at = observed_at or datetime.now(UTC)
    start = positioning_start or (
        seen_at.date() - timedelta(days=positioning_lookback_days)
    )
    supply_factory = supply_provider_factory or TreasurySupplyProvider
    positioning_factory = positioning_provider_factory or CftcTffProvider

    feeds: list[tuple[str, str, Feed]] = [
        (
            f"{SUPPLY_SOURCE}:{request_type}",
            SUPPLY_SOURCE,
            _supply_feed(
                supply_factory,
                request_type,
                seen_at,
                max_attempts,
                backoff_base_seconds,
                sleep_fn,
            ),
        )
        for request_type in supply_types
    ]
    feeds.append(
        (
            f"{POSITIONING_SOURCE}:tff",
            POSITIONING_SOURCE,
            _positioning_feed(
                positioning_factory,
                start,
                seen_at,
                max_attempts,
                backoff_base_seconds,
                sleep_fn,
            ),
        )
    )

    artifacts = 0
    created = 0
    unchanged = 0
    succeeded = 0
    failures: list[tuple[str, tuple[str, str]]] = []
    outcome_by_source: dict[str, list[str]] = {}

    with psycopg.connect(dsn) as conn:
        repo = Repository(conn)
        for feed_name, source, fetch in feeds:
            try:
                counts = _ingest_feed(repo, conn, fetch=fetch, seen_at=seen_at)
            except Exception as exc:
                logger.warning(
                    "macro market layer ingest failed for %s: %s", feed_name, repr(exc)
                )
                conn.rollback()
                parts = _error_parts(exc)
                failures.append((feed_name, parts))
                outcome_by_source.setdefault(source, []).append(
                    f"{feed_name}: {parts[0]}: {parts[1]}"
                )
                continue
            artifacts += counts[0]
            created += counts[1]
            unchanged += counts[2]
            succeeded += 1
            outcome_by_source.setdefault(source, [])

        for source, errors in outcome_by_source.items():
            repo.upsert_macro_source_status(
                source,
                status="degraded" if errors else "ok",
                attempted_at=seen_at,
                error_type="MacroMarketLayerFailures" if errors else None,
                error_message=("; ".join(errors)[:1000] if errors else None),
            )
        conn.commit()

    if failures:
        first_feed, (first_type, first_message) = failures[0]
        error_type: str | None = "MacroMarketLayerFailures"
        error_message: str | None = (
            f"{len(failures)} of {len(feeds)} feeds failed; "
            f"first {first_feed}: {first_type}: {first_message}"
        )[:1000]
    else:
        error_type = None
        error_message = None

    return MacroMarketLayerIngestResult(
        status="degraded" if failures else "ok",
        feeds_attempted=len(feeds),
        feeds_succeeded=succeeded,
        artifacts_seen=artifacts,
        observations_created=created,
        observations_unchanged=unchanged,
        failed_feeds=tuple(name for name, _ in failures),
        error_type=error_type,
        error_message=error_message,
    )


def _supply_feed(
    factory: Callable[[], Any],
    request_type: str,
    seen_at: datetime,
    max_attempts: int,
    backoff_base_seconds: float,
    sleep_fn: Callable[[float], None],
) -> Feed:
    def fetch() -> tuple[MacroSourceArtifact, Callable[[], list[MarketObservation]]]:
        raw_bytes, source_url = _with_retry(
            lambda provider: provider.fetch_auctions_payload(
                security_type=request_type
            ),
            factory=factory,
            max_attempts=max_attempts,
            backoff_base_seconds=backoff_base_seconds,
            sleep_fn=sleep_fn,
        )
        artifact = supply_artifact(
            raw_bytes,
            request_type=request_type,
            source_url=source_url,
            retrieved_at=seen_at,
        )
        return artifact, lambda: parse_supply_observations(
            raw_bytes, request_type=request_type, retrieved_at=seen_at
        )

    return fetch


def _positioning_feed(
    factory: Callable[[], Any],
    start: date,
    seen_at: datetime,
    max_attempts: int,
    backoff_base_seconds: float,
    sleep_fn: Callable[[float], None],
) -> Feed:
    def fetch() -> tuple[MacroSourceArtifact, Callable[[], list[MarketObservation]]]:
        raw_bytes, source_url = _with_retry(
            lambda provider: provider.fetch_treasury_payload(start=start),
            factory=factory,
            max_attempts=max_attempts,
            backoff_base_seconds=backoff_base_seconds,
            sleep_fn=sleep_fn,
        )
        artifact = positioning_artifact(
            raw_bytes, source_url=source_url, retrieved_at=seen_at
        )
        return artifact, lambda: parse_positioning_observations(raw_bytes)

    return fetch


def _ingest_feed(
    repo: Repository,
    conn: psycopg.Connection,
    *,
    fetch: Feed,
    seen_at: datetime,
) -> tuple[int, int, int]:
    artifact, parse = fetch()
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
    conn.commit()

    # Only now.  The bytes are safe, so a parse failure from here on costs this run and
    # leaves the payload that caused it queryable.
    outcome = repo.upsert_macro_series_observations(
        [
            observation_row(observation, artifact_id=artifact_id, artifact=artifact)
            for observation in parse()
        ],
        seen_at=seen_at,
    )
    conn.commit()
    return 1, outcome.created, outcome.unchanged


def _with_retry(
    call: Callable[[Any], tuple[bytes, str]],
    *,
    factory: Callable[[], Any],
    max_attempts: int,
    backoff_base_seconds: float,
    sleep_fn: Callable[[float], None],
) -> tuple[bytes, str]:
    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")
    for attempt in range(max_attempts):
        try:
            with factory() as provider:
                return call(provider)
        except Exception:
            if attempt + 1 == max_attempts:
                raise
            sleep_fn(backoff_base_seconds * (2**attempt))
    raise AssertionError("retry loop exhausted without returning or raising")


def _error_parts(exc: Exception) -> tuple[str, str]:
    return f"{type(exc).__module__}.{type(exc).__name__}", str(exc)
