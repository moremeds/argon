"""Point-in-time policy comparison assembly from immutable observations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from uw_scan.models.macro import (
    MacroEvidenceRef,
    PolicyComparison,
    PolicyPath,
    PolicyPathKind,
    PolicyPathPoint,
    PolicySourceFreshness,
)
from uw_scan.storage.repository import Repository

from .policy import assemble_policy_paths


@dataclass(frozen=True)
class _PathContract:
    kind: PolicyPathKind
    series_id: str
    sources: tuple[str, ...]


_CONTRACTS = (
    _PathContract(
        kind="actual",
        series_id="POLICY_PATH_ACTUAL",
        sources=("federal_reserve_fomc",),
    ),
    _PathContract(
        kind="committee_projection",
        series_id="POLICY_PATH_COMMITTEE_PROJECTION",
        sources=("federal_reserve_sep",),
    ),
    _PathContract(
        kind="dealer_expectations",
        series_id="POLICY_PATH_DEALER_EXPECTATIONS",
        sources=("new_york_fed_sme",),
    ),
    _PathContract(
        kind="market_implied",
        series_id="POLICY_PATH_MARKET_IMPLIED",
        sources=("frenzy_capital",),
    ),
)


def build_policy_comparison(
    repo: Repository, *, as_of: datetime
) -> PolicyComparison:
    rows: dict[PolicyPathKind, dict[str, Any]] = {}
    paths: list[PolicyPath] = []
    for contract in _CONTRACTS:
        row = repo.fetch_latest_macro_observation_as_of(
            contract.series_id,
            as_of,
            preferred_sources=contract.sources,
        )
        if row is None:
            continue
        rows[contract.kind] = row
        paths.append(_path_from_observation(contract, row))

    status_rows = repo.fetch_macro_source_statuses(
        [source for contract in _CONTRACTS for source in contract.sources]
    )
    freshness = {
        contract.kind: _freshness(contract, rows.get(contract.kind), status_rows, as_of)
        for contract in _CONTRACTS
    }
    return assemble_policy_paths(
        paths,
        as_of=as_of,
        freshness_by_kind=freshness,
    )


def _path_from_observation(
    contract: _PathContract, row: dict[str, Any]
) -> PolicyPath:
    value = row.get("value_jsonb")
    if not isinstance(value, dict) or value.get("kind") != contract.kind:
        raise ValueError(
            f"{contract.series_id} value kind does not match {contract.kind}"
        )
    raw_points = value.get("points")
    if not isinstance(raw_points, list):
        raise ValueError(f"{contract.series_id} points must be a list")
    evidence = MacroEvidenceRef.model_validate(row)
    return PolicyPath(
        kind=contract.kind,
        source=row["source"],
        source_record_id=row["source_record_id"],
        published_at=row["published_at"],
        available_at=row["available_at"],
        cost_class=row["cost_class"],
        delay_minutes=value.get("delay_minutes"),
        points=[PolicyPathPoint.model_validate(point) for point in raw_points],
        evidence_refs=[evidence],
    )


def _freshness(
    contract: _PathContract,
    row: dict[str, Any] | None,
    statuses: dict[str, dict[str, Any]],
    as_of: datetime,
) -> PolicySourceFreshness:
    source = row["source"] if row is not None else contract.sources[0]
    status = statuses.get(source)
    # The status table is current operational state, not an immutable history.
    # Never leak a later attempt into an earlier point-in-time replay.
    if status is None or status["last_attempt_at"] > as_of:
        return PolicySourceFreshness(source=source, status="missing")
    return PolicySourceFreshness.model_validate(status)
