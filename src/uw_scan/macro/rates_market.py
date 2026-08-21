"""The rates market layer as evidence: Treasury supply and futures positioning.

The rates engine has enumerated ``supply``, ``positioning`` and ``plumbing`` since MC0 and
reported all three absent ever since (``macro/rates.py:470``).  Not because nothing publishes
them -- both are already ingested nightly -- but because the tables they land in
(``rates_treasury_auctions``, ``rates_cftc_tff_weekly``) key on ``(..., as_of)`` and update
on conflict.  A value read back from one of those may already have been overwritten, so
promoting it to an immutable observation would launder a mutated number into the evidence
store.  This module fetches from the publishers instead, and the legacy tables stay what
they are: read models for the existing ``/rates`` surface.

Two things here are not mechanical, and both were measured before they were coded:

* **A supply series is keyed by the term AND the type.**  A 10-Year TIPS carries
  ``securityTerm='10-Year'`` and ``securityType='Note'`` exactly like a nominal 10-year note
  and is half the size.  Keyed on the term alone, the two interleave and the engine's
  multi-quarter-high rule reads the alternation as a supply collapse and recovery every
  quarter -- a signal produced entirely by a taxonomy error.  See spec 2.1.
* **A positioning row's availability comes from the publisher, never from a schedule.**  The
  CFTC payload carries no release column, and the rule that filled the gap -- report date
  plus three days -- is wrong on 36 of 205 releases and always EARLY.  Socrata's
  ``:created_at`` is the real load instant and is what this module uses.  See spec 3.2.

The module computes no state.  Sub-states, directions and contradictions belong to the
engine, which reads these rows back through :mod:`uw_scan.macro.evidence_store`.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Final
from zoneinfo import ZoneInfo

from uw_scan.macro_evidence import macro_artifact_content_identity
from uw_scan.models.macro import MacroFrequency, MacroSourceArtifact
from uw_scan.normalize import NormalizationError
from uw_scan.sources.cftc_tff import (
    TREASURY_TFF_CONTRACTS,
    CftcTffTreasuryRow,
    parse_treasury_rows,
)
from uw_scan.sources.treasury_supply import TreasuryAuctionRow, parse_auctions

from .contracts import CausalRole

SUPPLY_SOURCE: Final = "treasurydirect"
POSITIONING_SOURCE: Final = "cftc"
SUPPLY_PARSER_VERSION: Final = "rates_market_supply/1"
POSITIONING_PARSER_VERSION: Final = "rates_market_positioning/1"
DOMAIN: Final = "policy_rates"

_ET = ZoneInfo("America/New_York")

#: Nominal coupon terms.  Bills are excluded: they are cash management at weekly cadence,
#: not the duration supply a rates state describes, and the publisher's bill window is
#: twelve months deep against the coupon window's four years.
SUPPLY_TERMS: Final[tuple[tuple[str, str], ...]] = (
    ("2-Year", "Note"),
    ("3-Year", "Note"),
    ("5-Year", "Note"),
    ("7-Year", "Note"),
    ("10-Year", "Note"),
    ("20-Year", "Bond"),
    ("30-Year", "Bond"),
)

#: One request per instrument type, because the ``type`` parameter is what selects the
#: window.  ``TA_WS/securities/auctioned`` caps every response at 250 rows and ignores
#: ``startDate``/``endDate`` entirely (measured 2026-08-21), so the unfiltered call spends
#: its 250 rows across all types and reaches back only eighteen months -- six new issues per
#: coupon term, one above the five the engine's baseline needs.  ``type=Note`` reaches 2021
#: and ``type=Bond`` reaches 2012.  Asking per type is what makes the history deep enough to
#: be worth accruing.
SUPPLY_REQUEST_TYPES: Final[tuple[str, ...]] = ("Note", "Bond")

#: The reported trader categories, each its own factor.  Deliberately not summed: a
#: leveraged short is somebody else's long, so the categories move against each other by
#: construction and a single "positioning" number destroys the only information the report
#: carries.  ``other_rept`` is carried by the publisher but has no open-interest share in the
#: legacy row, so it is left out rather than half-represented.
POSITIONING_CATEGORIES: Final[tuple[str, ...]] = ("dealer", "asset_mgr", "lev_money")

#: Open interest is not a position; it is the denominator every share is stated against, and
#: a share cannot be checked without it.
POSITIONING_OPEN_INTEREST: Final = "open_interest"

_SUPPLY_CADENCE_DAYS: Final = 92
_POSITIONING_CADENCE_DAYS: Final = 7

#: Four places, not the legacy row's one.  ``lev_money_net_pct_oi`` on the legacy path is
#: quantized to 0.1 for display; a percentile taken over a rounded series collapses distinct
#: weeks onto the same value near the tails, which is exactly where the stretched label is
#: decided.
_PCT_PLACES: Final = Decimal("0.0001")


@dataclass(frozen=True)
class MarketSeriesContract:
    """One market-layer series' identity as an engine input."""

    series_id: str
    causal_role: CausalRole
    unit: str
    publisher_transform: str
    frequency: MacroFrequency
    cadence_days: int


def supply_series_id(security_term: str, instrument_type: str) -> str:
    return f"{security_term}|{instrument_type}"


def positioning_series_id(contract_code: str, field: str) -> str:
    return f"{contract_code}|{field}"


def _supply_contracts() -> dict[str, MarketSeriesContract]:
    return {
        supply_series_id(term, kind): MarketSeriesContract(
            series_id=supply_series_id(term, kind),
            causal_role="supply",
            unit="usd_offering_amount",
            publisher_transform="level",
            frequency="irregular",
            cadence_days=_SUPPLY_CADENCE_DAYS,
        )
        for term, kind in SUPPLY_TERMS
    }


def _positioning_contracts() -> dict[str, MarketSeriesContract]:
    out: dict[str, MarketSeriesContract] = {}
    for code in TREASURY_TFF_CONTRACTS:
        for field, unit in _positioning_fields():
            series_id = positioning_series_id(code, field)
            out[series_id] = MarketSeriesContract(
                series_id=series_id,
                causal_role="positioning",
                unit=unit,
                publisher_transform="level",
                frequency="weekly",
                cadence_days=_POSITIONING_CADENCE_DAYS,
            )
    return out


def _positioning_fields() -> tuple[tuple[str, str], ...]:
    fields: list[tuple[str, str]] = [(POSITIONING_OPEN_INTEREST, "contracts")]
    for category in POSITIONING_CATEGORIES:
        fields.append((f"{category}_net", "contracts_net"))
        fields.append((f"{category}_net_pct_oi", "pct_open_interest"))
    return tuple(fields)


#: Every market-layer series, enumerated.  A series id absent from here is refused rather
#: than ingested on the publisher's say-so: the unit and the causal role are this desk's
#: claims about what an input means, and a row that arrives without them would reach an
#: engine willing to compare a contract count against a percentage.
MARKET_SERIES_CONTRACT: Final[dict[str, MarketSeriesContract]] = {
    **_supply_contracts(),
    **_positioning_contracts(),
}


@dataclass(frozen=True)
class MarketObservation:
    """One published market-layer value with the instant it became knowable."""

    series_id: str
    causal_role: CausalRole
    period_end: date
    value_numeric: Decimal
    unit: str
    frequency: MacroFrequency
    published_at: datetime | None
    available_at: datetime
    #: How ``available_at`` was determined, so a conservative row is never mistaken for a
    #: publisher-timed one.  ``publisher_release`` and ``publisher_announcement`` come from
    #: the publisher; ``bulk_load_conservative`` and ``retrieval_conservative`` are R1's
    #: fallback and never claim knowability before we fetched.
    availability_basis: str
    source: str
    source_record_id: str
    parser_version: str


# --------------------------------------------------------------------------- supply


def supply_source_record_id(request_type: str) -> str:
    return f"treasurydirect-auctioned:{request_type}"


def supply_artifact(
    raw_bytes: bytes,
    *,
    request_type: str,
    source_url: str,
    retrieved_at: datetime,
) -> MacroSourceArtifact:
    content_hash, content_length = macro_artifact_content_identity(raw_bytes=raw_bytes)
    return MacroSourceArtifact(
        source=SUPPLY_SOURCE,
        source_kind="official",
        source_record_id=supply_source_record_id(request_type),
        source_url=source_url,
        # A query result, not a dated release: these bytes became available when we asked.
        published_at=None,
        available_at=retrieved_at,
        retrieved_at=retrieved_at,
        last_seen_at=retrieved_at,
        content_hash=content_hash,
        parser_version=SUPPLY_PARSER_VERSION,
        quality_status="valid",
        cost_class="free_official",
        media_type="application/json",
        content_length=content_length,
        # Every auction in the payload carries its own announcement date, so the payload
        # reports an announcement history rather than being an announcement.
        vintage_bearing=True,
        raw_bytes=raw_bytes,
    )


def parse_supply_observations(
    raw_bytes: bytes,
    *,
    request_type: str,
    retrieved_at: datetime,
) -> list[MarketObservation]:
    """Nominal new-issue offering sizes, one observation per auction.

    Three filters, each of which changes the series if dropped:

    * ``reopening is False`` -- a reopening adds to an outstanding security, so its size is
      a marginal add and comparing it against a new issue reads as a supply cut.
    * ``instrument_type == security_type`` -- the nominal filter (spec 2.1).
    * the ``(term, type)`` pair must be a registered series -- an unrecognised term is
      skipped rather than minted, because its unit and role would be unclaimed.
    """
    if not raw_bytes.strip():
        raise NormalizationError(
            f"TreasuryDirect returned an empty body for type={request_type}; an empty "
            "payload is a transport failure, never a zero-auction result"
        )
    rows = parse_auctions(raw_bytes)
    if not rows:
        raise NormalizationError(
            f"TreasuryDirect returned no readable auction for type={request_type}; the "
            "publisher does not stop auctioning, so this is a schema change"
        )
    out: list[MarketObservation] = []
    for row in rows:
        contract = _supply_contract_for(row)
        if contract is None:
            continue
        published_at, available_at, basis = _supply_availability(row, retrieved_at)
        assert row.offering_amount is not None  # narrowed by _supply_contract_for
        out.append(
            MarketObservation(
                series_id=contract.series_id,
                causal_role=contract.causal_role,
                period_end=row.auction_date,
                value_numeric=row.offering_amount,
                unit=contract.unit,
                frequency=contract.frequency,
                published_at=published_at,
                available_at=available_at,
                availability_basis=basis,
                source=SUPPLY_SOURCE,
                source_record_id=supply_source_record_id(request_type),
                parser_version=SUPPLY_PARSER_VERSION,
            )
        )
    return out


def _supply_contract_for(row: TreasuryAuctionRow) -> MarketSeriesContract | None:
    if row.reopening is not False or row.instrument_type != row.security_type:
        return None
    if row.offering_amount is None:
        return None
    return MARKET_SERIES_CONTRACT.get(
        supply_series_id(row.security_term, row.instrument_type)
    )


def _supply_availability(
    row: TreasuryAuctionRow, retrieved_at: datetime
) -> tuple[datetime | None, datetime, str]:
    """When the offering size became knowable.

    The announcement, not the auction: Treasury states the size about a week ahead, and
    dating it to the auction would misalign supply against a curve move that had already
    responded.  ``published_at`` stays ``None`` because the feed gives a date and no time of
    day -- an 11:00 ET stamp would read as a precision the publisher never gave.
    """
    if row.announcement_date is None:
        # R1's fallback: no publisher instant, so we claim only what we can defend --
        # that we knew it when we fetched it.
        return None, retrieved_at, "retrieval_conservative"
    return None, _et_midnight(row.announcement_date), "publisher_announcement"


def _et_midnight(day: date) -> datetime:
    """The start of a US publisher's day, in the publisher's own timezone.

    Deliberately Eastern rather than the UTC midnight ``sources/fred_macro._instant`` uses.
    Midnight UTC on an announcement date is 20:00 the PREVIOUS evening in Washington, so it
    claims the size was knowable before the day it was announced on had begun.  FRED's
    convention is not changed to match: ``available_at`` is part of the observation identity
    (``macro_observation_content_hash``), so shifting it would re-mint every vintage already
    stored rather than correct one.
    """
    return datetime.combine(day, datetime.min.time(), _ET).astimezone(UTC)


# ---------------------------------------------------------------------- positioning


POSITIONING_SOURCE_RECORD_ID: Final = "cftc-tff-futonly:interest-rates-us-treasury"


def positioning_artifact(
    raw_bytes: bytes,
    *,
    source_url: str,
    retrieved_at: datetime,
) -> MacroSourceArtifact:
    content_hash, content_length = macro_artifact_content_identity(raw_bytes=raw_bytes)
    return MacroSourceArtifact(
        source=POSITIONING_SOURCE,
        source_kind="official",
        source_record_id=POSITIONING_SOURCE_RECORD_ID,
        source_url=source_url,
        published_at=None,
        available_at=retrieved_at,
        retrieved_at=retrieved_at,
        last_seen_at=retrieved_at,
        content_hash=content_hash,
        parser_version=POSITIONING_PARSER_VERSION,
        quality_status="valid",
        cost_class="free_official",
        media_type="application/json",
        content_length=content_length,
        # Each row carries its own :created_at, so the payload reports a release history.
        vintage_bearing=True,
        raw_bytes=raw_bytes,
    )


def parse_positioning_observations(raw_bytes: bytes) -> list[MarketObservation]:
    """Trader-category nets and their open-interest shares, per contract per week."""
    if not raw_bytes.strip():
        raise NormalizationError(
            "CFTC TFF returned an empty body; an empty payload is a transport failure, "
            "never a zero-position result"
        )
    rows = parse_treasury_rows(raw_bytes)
    loads = load_event_instants(rows)
    out: list[MarketObservation] = []
    for row in rows:
        published_at, available_at, basis = _positioning_availability(row, loads)
        for field, value in _positioning_values(row):
            contract = MARKET_SERIES_CONTRACT.get(
                positioning_series_id(row.contract_code, field)
            )
            if contract is None or value is None:
                continue
            out.append(
                MarketObservation(
                    series_id=contract.series_id,
                    causal_role=contract.causal_role,
                    period_end=row.obs_date,
                    value_numeric=value,
                    unit=contract.unit,
                    frequency=contract.frequency,
                    published_at=published_at,
                    available_at=available_at,
                    availability_basis=basis,
                    source=POSITIONING_SOURCE,
                    source_record_id=POSITIONING_SOURCE_RECORD_ID,
                    parser_version=POSITIONING_PARSER_VERSION,
                )
            )
    return out


def load_event_instants(rows: list[CftcTffTreasuryRow]) -> frozenset[datetime]:
    """The ``:created_at`` values that are bulk loads rather than releases.

    A release covers one report date; every contract in that week's file shares its
    instant.  A ``:created_at`` spanning MORE than one report date is therefore a load
    event -- Socrata's own 2022-09-13 backfill stamps every report from 2006 to 2022 with
    one timestamp.  Treating that as a publication would claim sixteen years of weekly
    reports were all knowable on the same afternoon, which is lookahead on a scale no
    holiday rule could reach.
    """
    spans: dict[datetime, set[date]] = defaultdict(set)
    for row in rows:
        spans[row.release_at].add(row.obs_date)
    return frozenset(instant for instant, dates in spans.items() if len(dates) > 1)


def _positioning_availability(
    row: CftcTffTreasuryRow, loads: frozenset[datetime]
) -> tuple[datetime | None, datetime, str]:
    if row.release_at in loads:
        # R1: the true publication instant is unknown, so record none and let availability
        # rest on the load, which is late and therefore safe.
        return None, row.release_at, "bulk_load_conservative"
    return row.release_at, row.release_at, "publisher_release"


def _positioning_values(
    row: CftcTffTreasuryRow,
) -> list[tuple[str, Decimal | None]]:
    values: list[tuple[str, Decimal | None]] = [
        (POSITIONING_OPEN_INTEREST, row.open_interest)
    ]
    for category in POSITIONING_CATEGORIES:
        net = getattr(row, f"{category}_net")
        values.append((f"{category}_net", net))
        values.append((f"{category}_net_pct_oi", _share(net, row.open_interest)))
    return values


def _share(net: Decimal | None, open_interest: Decimal | None) -> Decimal | None:
    if net is None or open_interest is None or open_interest == 0:
        return None
    return (net / open_interest * Decimal(100)).quantize(_PCT_PLACES)


# ------------------------------------------------------------------------ persistence


def observation_row(
    observation: MarketObservation,
    *,
    artifact_id: int,
    artifact: MacroSourceArtifact,
) -> dict[str, Any]:
    """The row shape ``upsert_macro_series_observations`` writes.

    ``availability_basis`` is deliberately not persisted as a column: it is derivable from
    ``published_at`` being NULL, and a second field saying the same thing is a field that
    can disagree with the first.
    """
    return {
        "artifact_id": artifact_id,
        "domain": DOMAIN,
        "series_id": observation.series_id,
        "period_end": observation.period_end,
        "frequency": observation.frequency,
        "unit": observation.unit,
        "value_numeric": observation.value_numeric,
        "source": artifact.source,
        "source_record_id": artifact.source_record_id,
        "published_at": observation.published_at,
        "available_at": observation.available_at,
        "parser_version": observation.parser_version,
        "quality_status": "valid",
        "cost_class": artifact.cost_class,
    }
