"""Independent ingestion jobs for official policy-path evidence."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Protocol, TypeVar

import psycopg

from uw_scan.models.macro import MacroSourceArtifact
from uw_scan.sources.fed_funds_futures_path import (
    FedFundsFuturesPathProvider,
    parse_fed_funds_futures_snapshot,
)
from uw_scan.sources.fed_sep import FedSepProvider, parse_sep_release
from uw_scan.sources.fomc_statement import FomcStatementProvider, parse_fomc_statement
from uw_scan.sources.nyfed_sme import NyFedSmeProvider, parse_sme_release
from uw_scan.storage.repository import Repository

from .macro_policy_rows import (
    _market_observation,
    _sep_observation,
    _sme_observation,
    _statement_observation,
)

logger = logging.getLogger(__name__)


class _ContextProvider(Protocol):
    def __enter__(self) -> Any: ...

    def __exit__(self, *_exc: object) -> None: ...


_T = TypeVar("_T")


@dataclass(frozen=True)
class MacroPolicyIngestResult:
    source: str
    status: str
    artifacts_seen: int
    observations_seen: int
    releases_discovered: int = 0
    releases_succeeded: int = 0
    releases_failed: int = 0
    #: Releases whose evidence landed but whose facts did not. Named rather than
    #: counted so an operator can act without re-running the whole source.
    failed_release_keys: tuple[str, ...] = ()
    error_type: str | None = None
    error_message: str | None = None


def macro_fomc_statement_ingest_job(
    *,
    dsn: str,
    provider_factory: Callable[[], _ContextProvider] = FomcStatementProvider,
    observed_at: datetime | None = None,
    years: tuple[int, ...] | None = None,
    max_attempts: int = 3,
    backoff_base_seconds: float = 1.0,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> MacroPolicyIngestResult:
    seen_at = observed_at or datetime.now(UTC)
    requested_years = years or (seen_at.year,)
    try:
        outcomes = _fetch_with_retry(
            lambda provider: provider.fetch_outcomes(
                years=requested_years, retrieved_at=seen_at
            ),
            provider_factory=provider_factory,
            max_attempts=max_attempts,
            backoff_base_seconds=backoff_base_seconds,
            sleep_fn=sleep_fn,
        )
        return _persist_releases(
            dsn=dsn,
            source="federal_reserve_fomc",
            works=_works_from_outcomes(outcomes),
            parser=parse_fomc_statement,
            row_builder=_statement_observation,
            seen_at=seen_at,
        )
    except Exception as exc:
        logger.debug("macro ingest failed for federal_reserve_fomc: %s", repr(exc))
        return _record_failure(dsn, "federal_reserve_fomc", seen_at, exc)


def macro_sep_ingest_job(
    *,
    dsn: str,
    provider_factory: Callable[[], _ContextProvider] = FedSepProvider,
    observed_at: datetime | None = None,
    years: tuple[int, ...] | None = None,
    max_attempts: int = 3,
    backoff_base_seconds: float = 1.0,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> MacroPolicyIngestResult:
    seen_at = observed_at or datetime.now(UTC)
    requested_years = years or (seen_at.year,)
    try:
        outcomes = _fetch_with_retry(
            lambda provider: provider.fetch_outcomes(
                years=requested_years, retrieved_at=seen_at
            ),
            provider_factory=provider_factory,
            max_attempts=max_attempts,
            backoff_base_seconds=backoff_base_seconds,
            sleep_fn=sleep_fn,
        )
        return _persist_releases(
            dsn=dsn,
            source="federal_reserve_sep",
            works=_works_from_outcomes(outcomes),
            parser=parse_sep_release,
            row_builder=_sep_observation,
            seen_at=seen_at,
        )
    except Exception as exc:
        logger.debug("macro ingest failed for federal_reserve_sep: %s", repr(exc))
        return _record_failure(dsn, "federal_reserve_sep", seen_at, exc)


def macro_sme_ingest_job(
    *,
    dsn: str,
    survey_month: date | None = None,
    provider_factory: Callable[[], _ContextProvider] = NyFedSmeProvider,
    observed_at: datetime | None = None,
    max_attempts: int = 3,
    backoff_base_seconds: float = 1.0,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> MacroPolicyIngestResult:
    """Ingest one dealer survey: the newest by default, or a named month.

    Deliberately one month per call rather than a batch.  ``fetch_bundles``
    fails closed on a month the publisher does not list, so a batch would let a
    single unreachable survey erase every other release in the same run -- the
    exact failure ``_works_from_outcomes`` exists to avoid one level up.  Driven
    one at a time, a bad month records its own failure row and the rest still land.
    """
    seen_at = observed_at or datetime.now(UTC)
    try:
        bundle = _fetch_with_retry(
            lambda provider: (
                provider.fetch_latest_bundle(retrieved_at=seen_at)
                if survey_month is None
                else provider.fetch_bundles(
                    survey_months=[survey_month], retrieved_at=seen_at
                )[0]
            ),
            provider_factory=provider_factory,
            max_attempts=max_attempts,
            backoff_base_seconds=backoff_base_seconds,
            sleep_fn=sleep_fn,
        )
        return _persist_releases(
            dsn=dsn,
            source="new_york_fed_sme",
            works=[
                _ReleaseWork(
                    release_key=bundle.data_artifact.source_record_id,
                    artifacts=(bundle.data_artifact, bundle.report_artifact),
                    parsed_artifact=bundle.data_artifact,
                    bundle=bundle,
                )
            ],
            parser=lambda item: parse_sme_release(item, panel_type="Dealer"),
            row_builder=_sme_observation,
            seen_at=seen_at,
        )
    except Exception as exc:
        logger.debug("macro ingest failed for new_york_fed_sme: %s", repr(exc))
        return _record_failure(dsn, "new_york_fed_sme", seen_at, exc)


def macro_market_implied_ingest_job(
    *,
    dsn: str,
    current_target_range: str | None,
    provider_factory: Callable[[], _ContextProvider] = FedFundsFuturesPathProvider,
    observed_at: datetime | None = None,
    max_attempts: int = 3,
    backoff_base_seconds: float = 1.0,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> MacroPolicyIngestResult:
    seen_at = observed_at or datetime.now(UTC)
    try:
        bundle = _fetch_with_retry(
            lambda provider: provider.fetch_bundle(retrieved_at=seen_at),
            provider_factory=provider_factory,
            max_attempts=max_attempts,
            backoff_base_seconds=backoff_base_seconds,
            sleep_fn=sleep_fn,
        )
        return _persist_releases(
            dsn=dsn,
            source="frenzy_capital",
            works=[
                _ReleaseWork(
                    release_key=bundle.artifact.source_record_id,
                    artifacts=(bundle.artifact,),
                    parsed_artifact=bundle.artifact,
                    bundle=bundle,
                )
            ],
            parser=lambda item: parse_fed_funds_futures_snapshot(
                item, current_target_range=current_target_range
            ),
            row_builder=_market_observation,
            seen_at=seen_at,
        )
    except Exception as exc:
        logger.debug("macro ingest failed for frenzy_capital: %s", repr(exc))
        return _record_failure(dsn, "frenzy_capital", seen_at, exc)


def _fetch_with_retry(
    fetch: Callable[[Any], _T],
    *,
    provider_factory: Callable[[], _ContextProvider],
    max_attempts: int,
    backoff_base_seconds: float,
    sleep_fn: Callable[[float], None],
) -> _T:
    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")
    if backoff_base_seconds < 0:
        raise ValueError("backoff_base_seconds must be nonnegative")
    for attempt in range(max_attempts):
        try:
            with provider_factory() as provider:
                return fetch(provider)
        except Exception:
            if attempt + 1 == max_attempts:
                raise
            sleep_fn(backoff_base_seconds * (2**attempt))
    raise AssertionError("retry loop exhausted without returning or raising")


@dataclass(frozen=True)
class _ReleaseWork:
    """One release's exact evidence plus the catalog identity it belongs to.

    ``parsed_artifact`` is the artifact the parser actually reads.  For FOMC and
    SEP that is the accessible HTML, never the PDF: attributing the observation
    to the PDF would record a lineage the parser never touched.  Siblings are
    still persisted as evidence and linked as corroborating witnesses.

    ``release_type`` is None for sources the per-release catalog does not model
    (the dealer survey and the third-party market shadow are not FOMC releases),
    which keeps them out of the statement/SEP catalog without special-casing the
    isolation logic.
    """

    release_key: str
    artifacts: tuple[MacroSourceArtifact, ...]
    parsed_artifact: MacroSourceArtifact | None
    bundle: Any | None
    release_type: str | None = None
    event_date: date | None = None
    event_class: str | None = None
    discovery_url: str | None = None
    fetch_error: tuple[str, str] | None = None


@dataclass
class _ReleaseOutcome:
    artifacts_committed: int = 0
    observations: int = 0
    error: tuple[str, str] | None = None


def _works_from_outcomes(outcomes: Iterable[Any]) -> list[_ReleaseWork]:
    """Adapt provider fetch outcomes into per-release units of work.

    ``fetch_outcomes`` is used rather than ``fetch_bundles`` because the latter
    raises on the first bad candidate, which erases every other release in the
    same run and leaves a discovered-but-unfetchable release with no record at
    all.  Here each candidate becomes its own row whatever happened to it.
    """
    works: list[_ReleaseWork] = []
    for outcome in outcomes:
        candidate = outcome.candidate
        bundle = outcome.bundle
        if bundle is not None:
            artifacts = (bundle.primary_artifact, bundle.accessible_artifact)
            parsed = bundle.accessible_artifact
        else:
            artifacts = tuple(outcome.artifacts)
            parsed = None
        works.append(
            _ReleaseWork(
                release_key=candidate.release_key,
                artifacts=artifacts,
                parsed_artifact=parsed,
                bundle=bundle,
                release_type=candidate.release_type,
                event_date=candidate.event_date,
                event_class=candidate.event_class,
                discovery_url=candidate.discovery_url,
                fetch_error=(
                    (outcome.error_type, outcome.error_message)
                    if outcome.error_type
                    else None
                ),
            )
        )
    return works


def _persist_releases(
    *,
    dsn: str,
    source: str,
    works: list[_ReleaseWork],
    parser: Callable[[Any], Any],
    row_builder: Callable[[Any, int, MacroSourceArtifact], dict[str, Any]],
    seen_at: datetime,
) -> MacroPolicyIngestResult:
    """Ingest each release in its own transaction.

    One unreadable release used to roll back every observation in the batch,
    which is how a real 2026 run produced 10 artifacts and zero facts.  A
    failure here is scoped to its own release: earlier successes stay committed,
    the source is reported degraded, and the failed keys are named.
    """
    if not works:
        raise ValueError(f"{source} returned no release bundles")

    artifacts_seen = 0
    observations_seen = 0
    succeeded = 0
    failures: list[tuple[str, tuple[str, str]]] = []

    with psycopg.connect(dsn) as conn:
        repo = Repository(conn)
        for work in works:
            outcome = _ingest_release(
                repo,
                conn,
                source=source,
                work=work,
                parser=parser,
                row_builder=row_builder,
                seen_at=seen_at,
            )
            artifacts_seen += outcome.artifacts_committed
            observations_seen += outcome.observations
            if outcome.error is None:
                succeeded += 1
            else:
                failures.append((work.release_key, outcome.error))

        if failures:
            first_key, (first_type, first_message) = failures[0]
            error_type = "MacroReleaseFailures"
            error_message = (
                f"{len(failures)} of {len(works)} releases failed; "
                f"first {first_key}: {first_type}: {first_message}"
            )[:1000]
            repo.upsert_macro_source_status(
                source,
                status="degraded",
                attempted_at=seen_at,
                error_type=error_type,
                error_message=error_message,
            )
        else:
            error_type = None
            error_message = None
            repo.upsert_macro_source_status(source, status="ok", attempted_at=seen_at)
        conn.commit()

    return MacroPolicyIngestResult(
        source=source,
        status="degraded" if failures else "ok",
        artifacts_seen=artifacts_seen,
        observations_seen=observations_seen,
        releases_discovered=len(works),
        releases_succeeded=succeeded,
        releases_failed=len(failures),
        failed_release_keys=tuple(key for key, _ in failures),
        error_type=error_type,
        error_message=error_message,
    )


def _ingest_release(
    repo: Repository,
    conn: psycopg.Connection,
    *,
    source: str,
    work: _ReleaseWork,
    parser: Callable[[Any], Any],
    row_builder: Callable[[Any, int, MacroSourceArtifact], dict[str, Any]],
    seen_at: datetime,
) -> _ReleaseOutcome:
    outcome = _ReleaseOutcome()

    # Exact evidence commits before any parser is allowed to run, so a parse
    # failure can never cost us the bytes that prove what the publisher said.
    artifact_ids: dict[int, int] = {}
    try:
        for artifact in work.artifacts:
            artifact_ids[id(artifact)] = _insert_artifact(repo, artifact)
            outcome.artifacts_committed += 1
        conn.commit()
    except Exception as exc:
        logger.debug("macro artifact persistence failed: %s", repr(exc))
        conn.rollback()
        outcome.artifacts_committed = 0
        outcome.error = _error_parts(exc)
        _catalog(repo, conn, source=source, work=work, status="failed",
                 seen_at=seen_at, error=outcome.error, artifact=None)
        return outcome

    parsed = work.parsed_artifact
    parsed_id = artifact_ids.get(id(parsed)) if parsed is not None else None
    if work.bundle is None or parsed_id is None:
        # Discovery or fetch did not produce a complete release. The bytes we did
        # get are still evidence; the release is explicitly incomplete, never
        # silently absent.
        outcome.error = work.fetch_error or (
            "IncompleteRelease",
            f"{work.release_key} produced no parsable bundle",
        )
        witness = work.artifacts[0] if work.artifacts else None
        _catalog(
            repo, conn, source=source, work=work,
            status="artifact_only" if artifact_ids else "failed",
            seen_at=seen_at, error=outcome.error, artifact=witness,
            latest_artifact_id=(
                artifact_ids.get(id(witness)) if witness is not None else None
            ),
        )
        return outcome

    try:
        release = parser(work.bundle)
        persisted = repo.fetch_macro_artifact(parsed_id)
        if persisted is None:
            raise RuntimeError(f"persisted artifact {parsed_id} disappeared")
        effective = parsed.model_copy(
            update={
                "artifact_id": parsed_id,
                "available_at": persisted["available_at"],
                "published_at": persisted["published_at"],
                "retrieved_at": persisted["retrieved_at"],
                "last_seen_at": persisted["last_seen_at"],
            }
        )
        row = row_builder(release, parsed_id, effective)
        row["release_key"] = work.release_key
        obs_id, created = repo.upsert_macro_policy_observation(row, seen_at=seen_at)
        for artifact in work.artifacts:
            sibling_id = artifact_ids[id(artifact)]
            if sibling_id != parsed_id:
                repo.link_macro_observation_artifact(
                    obs_id=obs_id, artifact_id=sibling_id, relation="corroborates"
                )
        _catalog(
            repo, conn, source=source, work=work, status="ok", seen_at=seen_at,
            error=None, artifact=parsed, latest_artifact_id=parsed_id,
            success_artifact_id=parsed_id, commit=False,
        )
        conn.commit()
        outcome.observations = 1 if created else 0
        return outcome
    except Exception as exc:
        logger.debug("macro release %s failed: %s", work.release_key, repr(exc))
        conn.rollback()
        outcome.error = _error_parts(exc)
        _catalog(
            repo, conn, source=source, work=work, status="failed", seen_at=seen_at,
            error=outcome.error, artifact=parsed, latest_artifact_id=parsed_id,
        )
        return outcome


def _catalog(
    repo: Repository,
    conn: psycopg.Connection,
    *,
    source: str,
    work: _ReleaseWork,
    status: str,
    seen_at: datetime,
    error: tuple[str, str] | None,
    artifact: MacroSourceArtifact | None,
    latest_artifact_id: int | None = None,
    success_artifact_id: int | None = None,
    commit: bool = True,
) -> None:
    """Record this release's outcome, when the catalog models this source.

    ``artifact`` must be the one the ids point at: the catalog's foreign keys
    are composite over (artifact_id, source, source_record_id), so naming a
    different file of the same release would not resolve.
    """
    if work.release_type is None or work.event_date is None:
        return
    repo.upsert_macro_release_status(
        source=source,
        release_key=work.release_key,
        release_type=work.release_type,
        status=status,
        event_date=work.event_date,
        event_class=work.event_class,
        discovery_url=work.discovery_url or "",
        parser_version=(
            artifact.parser_version if artifact is not None else "unresolved"
        ),
        last_attempt_at=seen_at,
        artifact_source_record_id=(
            artifact.source_record_id if artifact is not None else None
        ),
        latest_artifact_id=latest_artifact_id,
        success_artifact_id=success_artifact_id,
        error_type=error[0] if error else None,
        error_message=error[1] if error else None,
    )
    if commit:
        conn.commit()


def _insert_artifact(repo: Repository, artifact: MacroSourceArtifact) -> int:
    return repo.insert_macro_artifact(
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
        raw_json=artifact.raw_json,
        raw_text=artifact.raw_text,
        raw_bytes=artifact.raw_bytes,
    )


def _record_failure(
    dsn: str, source: str, attempted_at: datetime, exc: Exception
) -> MacroPolicyIngestResult:
    error_type, error_message = _error_parts(exc)
    with psycopg.connect(dsn) as conn:
        repo = Repository(conn)
        repo.upsert_macro_source_status(
            source,
            status="degraded",
            attempted_at=attempted_at,
            error_type=error_type,
            error_message=error_message,
        )
        conn.commit()
    return MacroPolicyIngestResult(
        source=source,
        status="degraded",
        artifacts_seen=0,
        observations_seen=0,
        error_type=error_type,
        error_message=error_message,
    )


def _error_parts(exc: Exception) -> tuple[str, str]:
    return f"{type(exc).__module__}.{type(exc).__name__}", str(exc)
