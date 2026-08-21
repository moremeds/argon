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
from .rates_market import (
    MARKET_SERIES_CONTRACT,
    POSITIONING_CATEGORIES,
    POSITIONING_OPEN_INTEREST,
    SUPPLY_TERMS,
    positioning_series_id,
    supply_series_id,
)

#: Vintage-bearing publishers, in preference order.  A series we ingest from exactly one
#: source still needs the list: the repository ranks by it, and an empty ranking would
#: silently prefer whichever row sorted first.
PREFERRED_SOURCES: tuple[str, ...] = ("fred", "treasurydirect", "cftc")

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

#: Plumbing reads a 13-week momentum, so it needs the quarter behind it plus slack for a
#: weekly series whose publisher is late.
PLUMBING_HISTORY_DAYS = 120

#: Supply compares the latest new issue against the prior ``supply_baseline_quarters``.
#: The long end reissues quarterly, so five of them span five quarters; two years leaves
#: room for a term that skips a refunding without collapsing the baseline to four.
SUPPLY_HISTORY_DAYS = 730

#: Positioning is scored against its own trailing distribution, and this window is the one
#: that distribution was measured on: spec 4.2's percentiles come from 205 weekly releases,
#: 2022-09-13 to 2026-08-11.  Reading a longer window would compute a percentile against a
#: sample the STRETCHED thresholds were never calibrated on -- including the pre-2022
#: history, which is real but carries a single bulk-load availability instant.
POSITIONING_HISTORY_DAYS = 1460

#: The dollar anchor is scored against its own trailing year, so this must span one --
#: and it is a DAY count over a series whose releases are weekly.  The H.10 publishes the
#: week's daily observations together, 52.2 releases a year, so 400 days buys roughly a
#: year of releases plus the slack a late one costs.  Reading the value alone would make
#: "the dollar is strong" unfalsifiable: strong against what?
USD_HISTORY_DAYS = 400

#: The real index is monthly, so the same calendar window would give it 13 points -- too
#: few to say whether it confirms the nominal move or diverges from it.  Five years is 60
#: points, which spans the 2021-2022 tightening and its unwind, the one episode in the
#: sample where the nominal and real indices moved by materially different amounts.
USD_REAL_HISTORY_DAYS = 1830


@dataclass(frozen=True)
class SeriesEvidenceContract:
    """One series' identity as an engine input, assembled rather than restated."""

    series_id: str
    causal_role: CausalRole
    unit: str
    publisher_transform: str
    #: Which ingest owns this series.  Not decoration: ``macro_series_ingest`` asks FRED
    #: for its default series list, and without this it would ask FRED for a Treasury
    #: auction term and get a 400 it could not explain.
    source: str
    #: How far back this ROLE needs to see, which is a property of the question it
    #: answers rather than of the domain.  A curve attribution reads a month; a supply
    #: baseline reads five quarterly refundings.  One window for the domain would either
    #: starve supply or drag two years of daily curve prints into every ``inputs_hash``.
    #:
    #: ``None`` means the caller supplies the window.  Inflation does: its series are all
    #: monthly and its window is month-ALIGNED, which a day count cannot express, so a
    #: number here would be a value nothing reads -- and a value nothing reads is the one
    #: that silently becomes wrong.
    history_days: int | None = None


def _contract(
    series_id: str, causal_role: CausalRole, history_days: int | None = None
) -> SeriesEvidenceContract:
    source = SERIES_CONTRACT[series_id]
    return SeriesEvidenceContract(
        series_id=series_id,
        causal_role=causal_role,
        unit=source.unit,
        publisher_transform=source.publisher_transform,
        source="fred",
        history_days=history_days,
    )


def _market_contract(series_id: str, history_days: int) -> SeriesEvidenceContract:
    market = MARKET_SERIES_CONTRACT[series_id]
    return SeriesEvidenceContract(
        series_id=series_id,
        causal_role=market.causal_role,
        unit=market.unit,
        publisher_transform=market.publisher_transform,
        source="treasurydirect" if market.causal_role == "supply" else "cftc",
        history_days=history_days,
    )


#: Exactly the series the inflation engine declares load-bearing.  Loading more would
#: enlarge ``evidence_refs`` and move ``inputs_hash`` without changing a single factor --
#: identity noise that makes a real method change harder to see.
INFLATION_EVIDENCE: tuple[SeriesEvidenceContract, ...] = tuple(
    _contract(series_id, role)
    for series_id, (role, _cadence) in INFLATION_REQUIRED.items()
)

#: The benchmark Treasury future.  The market layer INGESTS all eight TFF contracts
#: because they arrive in one payload and cost nothing extra to store, but the state
#: READS one: the 10-year note future is the contract spec 4.2's distribution was
#: measured on, and adding the ultra-bond or the repo contract would enlarge every
#: ``inputs_hash`` without changing a factor.  Widening this is a method change and
#: belongs with the measurement that justifies it.
POSITIONING_CONTRACT_CODE = "043602"


def _positioning_evidence() -> tuple[SeriesEvidenceContract, ...]:
    """Each reported category, plus the denominator its share is stated against.

    The categories are deliberately not summed: a leveraged short is somebody else's
    long, so they move against each other by construction and one "positioning" number
    would destroy the only information the report carries.  Both the net and its share
    travel, so the raw sign is never inferred from a percentile label.
    """
    fields = [POSITIONING_OPEN_INTEREST]
    for category in POSITIONING_CATEGORIES:
        fields.extend((f"{category}_net", f"{category}_net_pct_oi"))
    return tuple(
        _market_contract(
            positioning_series_id(POSITIONING_CONTRACT_CODE, field),
            POSITIONING_HISTORY_DAYS,
        )
        for field in fields
    )


#: The market half of the rates state.  ``DGS10`` is tagged ``curve`` because that is
#: what it is, and the Cleveland reconciliation rule looks its two legs up by series id
#: rather than by role precisely so this tagging cannot mute it -- it stays dormant
#: until ``CLEVELAND_MODEL_NOMINAL_10Y`` has an ingest of its own, and nothing else.
#: There is nothing to reconcile a traded yield against yet.
#:
#: Supply, positioning and plumbing were absent here until MC3 Part A, and the reason was
#: never that nothing publishes them: it was that the only tables carrying them update on
#: conflict, so a value read back may already have been overwritten.  They now come from
#: the publishers as immutable observations -- see :mod:`uw_scan.macro.rates_market`.
RATES_EVIDENCE: tuple[SeriesEvidenceContract, ...] = (
    _contract("DGS10", "curve", RATES_HISTORY_DAYS),
    _contract("DFII10", "decomposition_component", RATES_HISTORY_DAYS),
    _contract("T10YIE", "decomposition_component", RATES_HISTORY_DAYS),
    # Plumbing: the two overnight rates the funding market clears at, plus the
    # balance-sheet quantity that drains against them.  None is a substitute for another,
    # so the reserve-balances slice that WRESBAL would have covered reports UNKNOWN
    # rather than borrowing a neighbour -- see ``sources/fred_macro`` for why that series
    # is unregistered, and the probe verdict for the measurement.
    _contract("SOFR", "plumbing", PLUMBING_HISTORY_DAYS),
    _contract("EFFR", "plumbing", PLUMBING_HISTORY_DAYS),
    _contract("RRPONTSYD", "plumbing", PLUMBING_HISTORY_DAYS),
    *(
        _market_contract(supply_series_id(term, kind), SUPPLY_HISTORY_DAYS)
        for term, kind in SUPPLY_TERMS
    ),
    *_positioning_evidence(),
)


#: The dollar half of the USD transmission state, and ALL of what USD owns.
#:
#: Two series and no more.  Relative policy, funding and positioning are USD factors too,
#: but they are owned upstream -- by MC2's rates state and by Part A's market layer -- and
#: USD reads them through those states rather than re-declaring them here.  Adding
#: ``EFFR`` or a positioning contract to this tuple would ingest the same publisher
#: payload under a second owner, and the two copies would drift on the first parser
#: change.  That is the double-count the design spec prohibits, and this tuple is where
#: it would happen.
#:
#: ``DTWEXBGS`` is the REQUIRED anchor: with it absent the state abstains rather than
#: promoting ``RTWEXBGS``.  They answer different questions -- a nominal index moving
#: while the real one does not is an inflation differential, which is a fact worth
#: reporting and not a reason to swap one for the other.
USD_EVIDENCE: tuple[SeriesEvidenceContract, ...] = (
    _contract("DTWEXBGS", "curve", USD_HISTORY_DAYS),
    _contract("RTWEXBGS", "decomposition_component", USD_REAL_HISTORY_DAYS),
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

    ``from_date`` overrides every contract's own window when given; passing ``None``
    lets each role read the history its question needs, which is the only way one call
    can serve a domain whose roles span a month and five quarterly refundings.

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
            from_date=_window_start(contract, as_of, from_date),
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
    # No domain-wide ``from_date``: each contract carries its own, because the curve
    # attribution reads a month while the supply baseline reads five quarterly
    # refundings and the positioning percentile reads four years.
    return load_domain_observations(repo, RATES_EVIDENCE, as_of=as_of)


def load_usd_observations(
    repo: Repository, *, as_of: datetime
) -> tuple[DomainObservation, ...]:
    # No domain-wide ``from_date``: the nominal anchor reads a year of weekly releases
    # and the real index reads five years of monthly ones, and one window would either
    # starve the second or drag five years of daily prints into every ``inputs_hash``.
    return load_domain_observations(repo, USD_EVIDENCE, as_of=as_of)


def _window_start(
    contract: SeriesEvidenceContract, as_of: datetime, from_date: date | None
) -> date:
    if from_date is not None:
        return from_date
    if contract.history_days is None:
        raise EvidenceContractError(
            f"{contract.series_id} declares no history window and the caller supplied "
            "none; reading it with no lower bound would pull the series' whole history "
            "into every inputs_hash"
        )
    return _days_before(as_of.date(), contract.history_days)


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
