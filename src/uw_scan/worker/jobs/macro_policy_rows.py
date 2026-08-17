"""Shape parsed policy releases into macro observation rows.

Split out of :mod:`uw_scan.worker.jobs.macro_policy_jobs` so orchestration
(fetch, isolate, persist, catalog) stays separate from row shaping.  Each
builder is a pure function of one parsed release plus the artifact the parser
actually read.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from uw_scan.models.macro import MacroSourceArtifact
from uw_scan.sources.fed_funds_futures_path import FedFundsFuturesSnapshot
from uw_scan.sources.fed_sep import SepRelease
from uw_scan.sources.fomc_statement import FomcStatementRelease
from uw_scan.sources.nyfed_sme import SmeRelease

logger = logging.getLogger(__name__)


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
                "target_range_lower_percent": _decimal_text(release.target_range_lower),
                "target_range_upper_percent": _decimal_text(release.target_range_upper),
                "action": release.action,
                "vote_status": release.vote_status,
                "vote_split": release.vote_split,
                # The dissent's composition carries most of the directional
                # signal, and a tally alone cannot recover it.  Empty lists with
                # voter_names_stated false mean the publisher named nobody --
                # never that the vote was unanimous.
                "voted_for": list(release.voted_for),
                "voted_against": list(release.voted_against),
                "voter_names_stated": release.voter_names_stated,
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
    value = {
        "kind": "committee_projection",
        "points": points,
        # The publisher labels some December releases EDT while the calendar is
        # EST.  The instant is resolved in Eastern time either way; the
        # disagreement is retained so a label drift leaves a durable trace.
        "declared_timezone": release.declared_timezone,
        "calendar_timezone": release.calendar_timezone,
    }
    return _observation_base(
        artifact_id=artifact_id,
        artifact=artifact,
        series_id="POLICY_PATH_COMMITTEE_PROJECTION",
        period_end=release.meeting_date,
        published_at=release.published_at,
        available_at=release.published_at,
        value=value,
        parser_version=release.parser_version,
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


def _sep_horizon_date(horizon: str) -> str | None:
    if not re.fullmatch(r"\d{4}", horizon):
        return None
    return date(int(horizon), 12, 31).isoformat()


def _decimal_text(value: Decimal) -> str:
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered
