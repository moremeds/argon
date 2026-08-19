"""Reading persisted evidence back into the shape the domain engines consume.

The engines take :class:`DomainObservation` objects; the database stores rows.  This
module is the only place the two meet, and it exists because the conversion is not
mechanical:

* ``causal_role`` is not a column.  What an input *does* in a state is a claim made by
  the engine, not a property of the bytes, so the role tables here are derived from the
  engines' own required-series tables rather than restated.
* ``publisher_transform`` is not a column either.  It comes from the source contract,
  which is the single place that knows ``MEDCPIM158SFRBCLE`` is an annualised monthly
  change and ``CORESTICKM159SFRBATL`` is a year-over-year one.  The two ids differ by
  one digit and their titles read as siblings.
* A stored ``unit`` that disagrees with the contract is a schema drift, not a detail.
  It fails closed here rather than reaching an engine that would happily compare a
  percent against an index level.

Point-in-time selection is the repository's job: ``fetch_macro_series_as_of`` already
returns one vintage per period -- the one in force at ``as_of`` -- so nothing here has
to reason about revisions.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from uw_scan.sources.fred_macro import SERIES_CONTRACT
from uw_scan.storage.repository import Repository

from .contracts import CausalRole, DomainObservation
from .inflation import REQUIRED as INFLATION_REQUIRED

#: Vintage-bearing publishers, in preference order.  A series we ingest from exactly one
#: source still needs the list: the repository ranks by it, and an empty ranking would
#: silently prefer whichever row sorted first.
PREFERRED_SOURCES: tuple[str, ...] = ("fred",)

#: Months of history the inflation engine needs behind the period it describes.  Not a
#: round number: a year-over-year rate at ``t`` reads ``t-12``, and the three-month
#: change of that rate reads back to ``t-15``.  Eighteen leaves three months of slack for
#: a publisher that is late, which is cheaper than a state that abstains because the
#: window was cut one month too short.
INFLATION_HISTORY_MONTHS = 18

#: Days of history the rates engine needs.  It reads the latest value of each market
#: series plus the same series roughly a month back, for the nominal-move attribution.
#: Forty-five days covers a month plus a holiday-thinned week of missing prints.
RATES_HISTORY_DAYS = 45


@dataclass(frozen=True)
class SeriesEvidenceContract:
    """One series' identity as an engine input, assembled rather than restated."""

    series_id: str
    causal_role: CausalRole
    unit: str
    publisher_transform: str


def _contract(series_id: str, causal_role: CausalRole) -> SeriesEvidenceContract:
    source = SERIES_CONTRACT[series_id]
    return SeriesEvidenceContract(
        series_id=series_id,
        causal_role=causal_role,
        unit=source.unit,
        publisher_transform=source.publisher_transform,
    )


#: Exactly the series the inflation engine declares load-bearing.  Loading more would
#: enlarge ``evidence_refs`` and move ``inputs_hash`` without changing a single factor --
#: identity noise that makes a real method change harder to see.
INFLATION_EVIDENCE: tuple[SeriesEvidenceContract, ...] = tuple(
    _contract(series_id, role)
    for series_id, (role, _cadence) in INFLATION_REQUIRED.items()
)

#: The market half of the rates state.  ``DGS10`` is tagged ``curve`` because that is
#: what it is; the Cleveland reconciliation rule reads ``decomposition_component`` and
#: therefore stays dormant until ``CLEVELAND_MODEL_NOMINAL_10Y`` has an ingest of its
#: own -- there is nothing to reconcile a traded yield against yet.  Supply, positioning
#: and plumbing are absent for the same reason: no free vintage-bearing source for them
#: is ingested, and the engine reports their absence rather than inventing them.
RATES_EVIDENCE: tuple[SeriesEvidenceContract, ...] = (
    _contract("DGS10", "curve"),
    _contract("DFII10", "decomposition_component"),
    _contract("T10YIE", "decomposition_component"),
)


class EvidenceContractError(ValueError):
    """A stored row does not match the contract the engine was built against."""


def load_domain_observations(
    repo: Repository,
    contracts: Sequence[SeriesEvidenceContract],
    *,
    as_of: datetime,
    from_date: date | None = None,
    preferred_sources: Sequence[str] = PREFERRED_SOURCES,
) -> tuple[DomainObservation, ...]:
    """Every stored observation these contracts cover that was published by ``as_of``.

    Returns them carrying their ``obs_id``, which is what makes a state built on them
    persistable: a state whose evidence cannot be pointed at is refused by the store.
    """
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    out: list[DomainObservation] = []
    for contract in contracts:
        rows = repo.fetch_macro_series_as_of(
            contract.series_id,
            as_of,
            from_date=from_date,
            preferred_sources=preferred_sources,
        )
        out.extend(_observation(contract, row) for row in rows)
    return tuple(out)


def load_inflation_observations(
    repo: Repository, *, as_of: datetime
) -> tuple[DomainObservation, ...]:
    return load_domain_observations(
        repo,
        INFLATION_EVIDENCE,
        as_of=as_of,
        from_date=_months_before(as_of.date(), INFLATION_HISTORY_MONTHS),
    )


def load_rates_observations(
    repo: Repository, *, as_of: datetime
) -> tuple[DomainObservation, ...]:
    return load_domain_observations(
        repo,
        RATES_EVIDENCE,
        as_of=as_of,
        from_date=_days_before(as_of.date(), RATES_HISTORY_DAYS),
    )


def _observation(
    contract: SeriesEvidenceContract, row: dict[str, Any]
) -> DomainObservation:
    value = row["value_numeric"]
    if value is None:
        raise EvidenceContractError(
            f"{contract.series_id} observation {row['obs_id']} for "
            f"{row['period_end']} carries no numeric value; a series the engine reads "
            "as a number must not be stored as text or JSON"
        )
    if row["unit"] != contract.unit:
        raise EvidenceContractError(
            f"{contract.series_id} observation {row['obs_id']} is stored in "
            f"{row['unit']!r} but the source contract says {contract.unit!r}; the "
            "publisher changed the series or the ingest wrote the wrong contract"
        )
    return DomainObservation(
        series_id=contract.series_id,
        causal_role=contract.causal_role,
        period_end=row["period_end"],
        value=Decimal(str(value)),
        unit=row["unit"],
        publisher_transform=contract.publisher_transform,
        available_at=row["available_at"],
        source=row["source"],
        source_kind=row["source_kind"],
        cost_class=row["cost_class"],
        quality_status=row["quality_status"],
        obs_id=row["obs_id"],
        artifact_id=row["artifact_id"],
    )


def _months_before(day: date, months: int) -> date:
    total = day.year * 12 + (day.month - 1) - months
    return date(total // 12, total % 12 + 1, 1)


def _days_before(day: date, days: int) -> date:
    return date.fromordinal(day.toordinal() - days)
