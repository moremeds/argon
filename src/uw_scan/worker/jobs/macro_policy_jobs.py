"""Independent ingestion jobs for official policy-path evidence."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Protocol, TypeVar

import psycopg

from uw_scan.macro_evidence import macro_observation_content_hash
from uw_scan.models.macro import MacroSourceArtifact
from uw_scan.sources.fed_sep import FedSepProvider, SepRelease, parse_sep_release
from uw_scan.sources.fed_funds_futures_path import (
    FedFundsFuturesPathProvider,
    FedFundsFuturesSnapshot,
    parse_fed_funds_futures_snapshot,
)
from uw_scan.sources.fomc_statement import (
    FomcStatementProvider,
    FomcStatementRelease,
    parse_fomc_statement,
)
from uw_scan.sources.nyfed_sme import NyFedSmeProvider, SmeRelease, parse_sme_release
from uw_scan.storage.repository import Repository


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
        bundles = _fetch_with_retry(
            lambda provider: provider.fetch_bundles(
                years=requested_years, retrieved_at=seen_at
            ),
            provider_factory=provider_factory,
            max_attempts=max_attempts,
            backoff_base_seconds=backoff_base_seconds,
            sleep_fn=sleep_fn,
        )
        return _persist_release_bundles(
            dsn=dsn,
            source="federal_reserve_fomc",
            bundles=bundles,
            artifacts_for=lambda bundle: (
                bundle.primary_artifact,
                bundle.accessible_artifact,
            ),
            primary_for=lambda bundle: bundle.primary_artifact,
            parser=parse_fomc_statement,
            row_builder=_statement_observation,
            seen_at=seen_at,
        )
    except Exception as exc:
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
        bundles = _fetch_with_retry(
            lambda provider: provider.fetch_bundles(
                years=requested_years, retrieved_at=seen_at
            ),
            provider_factory=provider_factory,
            max_attempts=max_attempts,
            backoff_base_seconds=backoff_base_seconds,
            sleep_fn=sleep_fn,
        )
        return _persist_release_bundles(
            dsn=dsn,
            source="federal_reserve_sep",
            bundles=bundles,
            artifacts_for=lambda bundle: (
                bundle.primary_artifact,
                bundle.accessible_artifact,
            ),
            primary_for=lambda bundle: bundle.primary_artifact,
            parser=parse_sep_release,
            row_builder=_sep_observation,
            seen_at=seen_at,
        )
    except Exception as exc:
        return _record_failure(dsn, "federal_reserve_sep", seen_at, exc)


def macro_sme_ingest_job(
    *,
    dsn: str,
    provider_factory: Callable[[], _ContextProvider] = NyFedSmeProvider,
    observed_at: datetime | None = None,
    max_attempts: int = 3,
    backoff_base_seconds: float = 1.0,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> MacroPolicyIngestResult:
    seen_at = observed_at or datetime.now(UTC)
    try:
        bundle = _fetch_with_retry(
            lambda provider: provider.fetch_latest_bundle(retrieved_at=seen_at),
            provider_factory=provider_factory,
            max_attempts=max_attempts,
            backoff_base_seconds=backoff_base_seconds,
            sleep_fn=sleep_fn,
        )
        return _persist_release_bundles(
            dsn=dsn,
            source="new_york_fed_sme",
            bundles=[bundle],
            artifacts_for=lambda item: (item.data_artifact, item.report_artifact),
            primary_for=lambda item: item.data_artifact,
            parser=lambda item: parse_sme_release(item, panel_type="Dealer"),
            row_builder=_sme_observation,
            seen_at=seen_at,
        )
    except Exception as exc:
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
        return _persist_release_bundles(
            dsn=dsn,
            source="frenzy_capital",
            bundles=[bundle],
            artifacts_for=lambda item: (item.artifact,),
            primary_for=lambda item: item.artifact,
            parser=lambda item: parse_fed_funds_futures_snapshot(
                item, current_target_range=current_target_range
            ),
            row_builder=_market_observation,
            seen_at=seen_at,
        )
    except Exception as exc:
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


def _persist_release_bundles(
    *,
    dsn: str,
    source: str,
    bundles: Iterable[Any],
    artifacts_for: Callable[[Any], tuple[MacroSourceArtifact, ...]],
    primary_for: Callable[[Any], MacroSourceArtifact],
    parser: Callable[[Any], Any],
    row_builder: Callable[[Any, int, MacroSourceArtifact], dict[str, Any]],
    seen_at: datetime,
) -> MacroPolicyIngestResult:
    materialized = list(bundles)
    if not materialized:
        raise ValueError(f"{source} returned no release bundles")
    artifact_ids: dict[int, int] = {}
    artifact_count = 0
    with psycopg.connect(dsn) as conn:
        repo = Repository(conn)
        # Evidence lands and commits before any parser is allowed to run.
        for bundle in materialized:
            for artifact in artifacts_for(bundle):
                artifact_ids[id(artifact)] = _insert_artifact(repo, artifact)
                artifact_count += 1
        conn.commit()

        try:
            rows: list[dict[str, Any]] = []
            for bundle in materialized:
                release = parser(bundle)
                primary = primary_for(bundle)
                artifact_id = artifact_ids[id(primary)]
                persisted = repo.fetch_macro_artifact(artifact_id)
                if persisted is None:
                    raise RuntimeError(f"persisted artifact {artifact_id} disappeared")
                effective_primary = primary.model_copy(
                    update={
                        "artifact_id": artifact_id,
                        "available_at": persisted["available_at"],
                        "published_at": persisted["published_at"],
                        "retrieved_at": persisted["retrieved_at"],
                        "last_seen_at": persisted["last_seen_at"],
                    }
                )
                rows.append(row_builder(release, artifact_id, effective_primary))
            for row in rows:
                row["content_hash"] = macro_observation_content_hash(row)
            repo.insert_macro_observations(rows, seen_at=seen_at)
            repo.upsert_macro_source_status(source, status="ok", attempted_at=seen_at)
            conn.commit()
        except Exception as exc:
            conn.rollback()
            error_type, error_message = _error_parts(exc)
            repo.upsert_macro_source_status(
                source,
                status="degraded",
                attempted_at=seen_at,
                error_type=error_type,
                error_message=error_message,
            )
            conn.commit()
            return MacroPolicyIngestResult(
                source=source,
                status="degraded",
                artifacts_seen=artifact_count,
                observations_seen=0,
                error_type=error_type,
                error_message=error_message,
            )
    return MacroPolicyIngestResult(
        source=source,
        status="ok",
        artifacts_seen=artifact_count,
        observations_seen=len(rows),
    )


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


def _statement_observation(
    release: FomcStatementRelease,
    artifact_id: int,
    artifact: MacroSourceArtifact,
) -> dict[str, Any]:
    midpoint = (release.target_range_lower + release.target_range_upper) / 2
    value = {
        "kind": "actual",
        "parser_version": release.parser_version,
        "points": [
            {
                "horizon": "current",
                "horizon_date": release.meeting_date.isoformat(),
                "rate_percent": _decimal_text(midpoint),
                "target_range_lower": _decimal_text(release.target_range_lower),
                "target_range_upper": _decimal_text(release.target_range_upper),
                "target_range_lower_percent": _decimal_text(
                    release.target_range_lower
                ),
                "target_range_upper_percent": _decimal_text(
                    release.target_range_upper
                ),
                "action": release.action,
                "vote_status": release.vote_status,
                "vote_split": release.vote_split,
            }
        ],
    }
    return _observation_base(
        artifact_id=artifact_id,
        artifact=artifact,
        series_id="POLICY_PATH_ACTUAL",
        period_end=release.meeting_date,
        published_at=release.published_at,
        available_at=release.published_at,
        value=value,
        parser_version=release.parser_version,
    )


def _sep_observation(
    release: SepRelease,
    artifact_id: int,
    artifact: MacroSourceArtifact,
) -> dict[str, Any]:
    points = []
    for projection in release.projections:
        if projection.variable != "federal_funds_rate":
            continue
        points.append(
            {
                "horizon": projection.horizon,
                "horizon_date": _sep_horizon_date(projection.horizon),
                "rate_percent": _decimal_text(projection.median),
                "central_tendency": [
                    _decimal_text(projection.central_tendency[0]),
                    _decimal_text(projection.central_tendency[1]),
                ],
                "central_tendency_lower_percent": _decimal_text(
                    projection.central_tendency[0]
                ),
                "central_tendency_upper_percent": _decimal_text(
                    projection.central_tendency[1]
                ),
                "range": [
                    _decimal_text(projection.range[0]),
                    _decimal_text(projection.range[1]),
                ],
                "range_lower_percent": _decimal_text(projection.range[0]),
                "range_upper_percent": _decimal_text(projection.range[1]),
                "participant_distribution": [
                    {
                        "rate_percent": _decimal_text(item.value),
                        "participant_count": item.participant_count,
                    }
                    for item in projection.participant_distribution
                ],
            }
        )
    value = {"kind": "committee_projection", "points": points}
    return _observation_base(
        artifact_id=artifact_id,
        artifact=artifact,
        series_id="POLICY_PATH_COMMITTEE_PROJECTION",
        period_end=release.meeting_date,
        published_at=release.published_at,
        available_at=release.published_at,
        value=value,
    )


def _sme_observation(
    release: SmeRelease,
    artifact_id: int,
    artifact: MacroSourceArtifact,
) -> dict[str, Any]:
    distributions = {
        (item.horizon, item.horizon_date): item
        for item in release.probability_distributions
    }
    points = []
    for point in release.path_points:
        distribution = distributions.get((point.horizon, point.horizon_date))
        points.append(
            {
                "horizon": point.horizon,
                "horizon_date": (
                    point.horizon_date.isoformat()
                    if point.horizon_date is not None
                    else None
                ),
                "rate_percent": _decimal_text(point.median),
                "median": _decimal_text(point.median),
                "p25": _decimal_text(point.p25),
                "p75": _decimal_text(point.p75),
                "p25_percent": _decimal_text(point.p25),
                "p75_percent": _decimal_text(point.p75),
                "respondent_count": point.respondent_count,
                "probability_distribution": (
                    [
                        {
                            "label": bucket.label,
                            "lower_bound_percent": (
                                _decimal_text(bucket.lower_bound)
                                if bucket.lower_bound is not None
                                else None
                            ),
                            "upper_bound_percent": (
                                _decimal_text(bucket.upper_bound)
                                if bucket.upper_bound is not None
                                else None
                            ),
                            "probability_percent": _decimal_text(bucket.probability),
                        }
                        for bucket in distribution.buckets
                    ]
                    if distribution is not None
                    else []
                ),
            }
        )
    value = {"kind": "dealer_expectations", "points": points}
    return _observation_base(
        artifact_id=artifact_id,
        artifact=artifact,
        series_id="POLICY_PATH_DEALER_EXPECTATIONS",
        period_end=release.response_due_date,
        published_at=release.published_at,
        available_at=artifact.available_at,
        value=value,
    )


def _market_observation(
    release: FedFundsFuturesSnapshot,
    artifact_id: int,
    artifact: MacroSourceArtifact,
) -> dict[str, Any]:
    points = []
    for point in release.points:
        assert point.implied_rate is not None
        probabilities = point.probabilities or {}
        points.append(
            {
                "horizon": point.label,
                "horizon_date": point.meeting_date.isoformat(),
                "rate_percent": _decimal_text(point.implied_rate),
                "probability_distribution": [
                    {
                        "label": label,
                        "probability_percent": _decimal_text(probability * 100),
                    }
                    for label, probability in sorted(probabilities.items())
                ],
            }
        )
    value = {
        "kind": "market_implied",
        "delay_status": release.delay_status,
        "delay_minutes": release.delay_minutes,
        "points": points,
    }
    return _observation_base(
        artifact_id=artifact_id,
        artifact=artifact,
        series_id="POLICY_PATH_MARKET_IMPLIED",
        period_end=artifact.available_at.date(),
        published_at=None,
        available_at=artifact.available_at,
        value=value,
    )


def _observation_base(
    *,
    artifact_id: int,
    artifact: MacroSourceArtifact,
    series_id: str,
    period_end: date,
    published_at: datetime | None,
    available_at: datetime,
    value: dict[str, Any],
    parser_version: str | None = None,
) -> dict[str, Any]:
    return {
        "artifact_id": artifact_id,
        "domain": "policy_rates",
        "series_id": series_id,
        "period_end": period_end,
        "frequency": "event",
        "unit": "policy_path_json",
        "value_json": value,
        "source": artifact.source,
        "source_record_id": artifact.source_record_id,
        "published_at": published_at,
        "available_at": available_at,
        "parser_version": parser_version or artifact.parser_version,
        "quality_status": "partial",
        "cost_class": artifact.cost_class,
    }


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


def _sep_horizon_date(horizon: str) -> str | None:
    try:
        return date(int(horizon), 12, 31).isoformat()
    except ValueError:
        return None


def _decimal_text(value: Decimal) -> str:
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered
