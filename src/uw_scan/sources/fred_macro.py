"""ALFRED-backed adapter for realized inflation and market compensation series.

Why FRED and not the statistical agency: BLS returns HTTP 403 to this desk on every
host, and BEA answers a missing credential with HTTP 200 and a zero-length body.
Neither publishes vintages at all.  ALFRED does -- every observation carries the
``[realtime_start, realtime_end)`` window during which it was the published value --
and that vintage record is the Federal Reserve Bank of St. Louis's own first-party
product, not a copy of a BLS release.  Measured evidence:
``docs/research/2026-08-18-mc2-inflation-source-probe/``.

The adapter reports what was published and computes nothing.  Year-over-year and
annualised transforms belong to the state engine, because the transform is a property
of the series definition rather than of the fetch.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Final, Literal

from uw_scan.macro_evidence import macro_artifact_content_identity
from uw_scan.models.macro import MacroDomain, MacroFrequency, MacroSourceArtifact
from uw_scan.normalize import NormalizationError

SOURCE: Final = "fred"
PARSER_VERSION: Final = "fred_macro/1"

#: FRED encodes a series' transform in its id suffix, not its title.  ``M158`` is a
#: month-over-month change at an annual rate and ``M159`` is a change from a year ago,
#: while the two titles read as siblings.  Recording the transform explicitly is what
#: lets the engine refuse to combine two factors that are not commensurable.
PublisherTransform = Literal["index_level", "mom_annualized", "yoy", "level"]


@dataclass(frozen=True)
class FredSeriesContract:
    series_id: str
    domain: MacroDomain
    frequency: MacroFrequency
    unit: str
    publisher_transform: PublisherTransform
    #: Expected days between releases; the freshness term decays against this.
    cadence_days: int


def _contract(
    series_id: str,
    domain: MacroDomain,
    frequency: MacroFrequency,
    unit: str,
    transform: PublisherTransform,
    cadence_days: int,
) -> FredSeriesContract:
    return FredSeriesContract(
        series_id=series_id,
        domain=domain,
        frequency=frequency,
        unit=unit,
        publisher_transform=transform,
        cadence_days=cadence_days,
    )


SERIES_CONTRACT: Final[dict[str, FredSeriesContract]] = {
    contract.series_id: contract
    for contract in (
        # Realized inflation.  Core PCE is the state basis because the FOMC's 2 percent
        # objective is stated on PCE; CPI arrives ~2 weeks earlier and corroborates.
        _contract(
            "PCEPILFE", "inflation", "monthly", "index_2017_100_sa", "index_level", 31
        ),
        _contract(
            "PCEPI", "inflation", "monthly", "index_2017_100_sa", "index_level", 31
        ),
        _contract(
            "CPILFESL",
            "inflation",
            "monthly",
            "index_1982_84_100_sa",
            "index_level",
            31,
        ),
        _contract(
            "CPIAUCSL",
            "inflation",
            "monthly",
            "index_1982_84_100_sa",
            "index_level",
            31,
        ),
        # Breadth and stickiness, already transformed by their publishers.
        _contract(
            "MEDCPIM158SFRBCLE",
            "inflation",
            "monthly",
            "percent_change_annual_rate",
            "mom_annualized",
            31,
        ),
        _contract(
            "TRMMEANCPIM158SFRBCLE",
            "inflation",
            "monthly",
            "percent_change_annual_rate",
            "mom_annualized",
            31,
        ),
        _contract(
            "CORESTICKM159SFRBATL",
            "inflation",
            "monthly",
            "percent_change_from_year_ago",
            "yoy",
            31,
        ),
        # Expectations.  Survey and market compensation are kept apart on purpose:
        # a breakeven is expected inflation plus a risk premium minus TIPS liquidity.
        _contract("MICH", "inflation", "monthly", "percent", "level", 31),
        _contract("T10YIE", "inflation", "daily", "percent", "level", 1),
        _contract("T5YIFR", "inflation", "daily", "percent", "level", 1),
        # Rates.
        _contract("DGS10", "policy_rates", "daily", "percent", "level", 1),
        _contract("DFII10", "policy_rates", "daily", "percent", "level", 1),
        # Funding plumbing.  Two overnight rates the market clears at, plus the
        # balance-sheet quantity that drains against them.
        #
        # WRESBAL -- reserve balances -- is deliberately NOT here, and the reason is a
        # property of this table's shape.  A contract declares ONE unit per series, and
        # FRED republished WRESBAL's entire history on 2025-11-13 with every value
        # multiplied by a thousand: the vintage of period 2025-06-04 in force until
        # 2025-11-12 reads 3294.381 and the one in force after reads 3294381.0.  Measured
        # across 566 periods, every ratio is exactly 1000.0.  So the unit is a property of
        # the VINTAGE, which this contract cannot express and the observations endpoint
        # does not report -- any replay with an as_of before that date would read billions
        # labelled millions, silently and plausibly.  See the probe verdict.
        _contract("SOFR", "policy_rates", "daily", "percent", "level", 1),
        _contract("EFFR", "policy_rates", "daily", "percent", "level", 1),
        _contract("RRPONTSYD", "policy_rates", "daily", "billions_usd", "level", 1),
    )
}


@dataclass(frozen=True)
class FredSeriesObservation:
    """One published value, tied to the window in which it was the published value."""

    series_id: str
    domain: MacroDomain
    frequency: MacroFrequency
    unit: str
    publisher_transform: PublisherTransform
    period_end: date
    value_numeric: Decimal
    available_at: datetime
    #: Instant this value stopped being current; ``None`` while it still is.
    superseded_at: datetime | None
    parser_version: str
    #: Identity of the published datum, independent of which fetch carried it.
    #: Excludes ``artifact_id`` for the same reason MC1's policy semantic hash does:
    #: re-fetching an unchanged series creates a new artifact but not a new fact.
    vintage_hash: str


@dataclass(frozen=True)
class FredSeriesBundle:
    series_id: str
    contract: FredSeriesContract
    artifact: MacroSourceArtifact
    raw_bytes: bytes

    @classmethod
    def from_bytes(
        cls,
        *,
        series_id: str,
        source_url: str,
        raw_bytes: bytes,
        retrieved_at: datetime,
    ) -> "FredSeriesBundle":
        contract = SERIES_CONTRACT.get(series_id)
        if contract is None:
            raise NormalizationError(
                f"FRED series {series_id!r} is unregistered; add a FredSeriesContract "
                "with its unit and publisher transform before ingesting it"
            )
        content_hash, content_length = macro_artifact_content_identity(
            raw_bytes=raw_bytes
        )
        artifact = MacroSourceArtifact(
            source=SOURCE,
            # FRED redistributes BLS and BEA statistics, so this is not `official`.
            # What we consume -- the vintage-stamped series -- is FRED's own product.
            source_kind="first_party_publisher",
            source_record_id=f"fred-series:{series_id}",
            source_url=source_url,
            # A series query is a rolling read, not a dated release: these bytes
            # became available when we asked for them and never earlier.
            published_at=None,
            available_at=retrieved_at,
            retrieved_at=retrieved_at,
            last_seen_at=retrieved_at,
            content_hash=content_hash,
            parser_version=PARSER_VERSION,
            quality_status="valid",
            cost_class="free_publisher",
            media_type="application/json",
            content_length=content_length,
            # Every row in this payload carries its own realtime_start, so the payload
            # reports a publication history rather than being a publication.
            vintage_bearing=True,
            raw_bytes=raw_bytes,
        )
        return cls(
            series_id=series_id,
            contract=contract,
            artifact=artifact,
            raw_bytes=raw_bytes,
        )


def parse_fred_series(bundle: FredSeriesBundle) -> list[FredSeriesObservation]:
    """Normalize one ALFRED payload into published values with their vintages.

    Fails closed on anything it does not understand.  In particular an empty body is
    an error rather than an empty result: that is precisely how BEA reports a missing
    credential, and a source that answers "no data" to an auth failure will otherwise
    be recorded as having legitimately published nothing.
    """
    if not bundle.raw_bytes.strip():
        raise NormalizationError(
            f"FRED series {bundle.series_id} returned an empty body; an empty payload is a "
            "transport or credential failure, never a zero-row result"
        )
    try:
        payload: Any = json.loads(bundle.raw_bytes)
    except json.JSONDecodeError as exc:
        raise NormalizationError(
            f"FRED series {bundle.series_id} payload is not JSON: {exc!r}"
        ) from exc
    if not isinstance(payload, dict) or "observations" not in payload:
        raise NormalizationError(
            f"FRED series {bundle.series_id} payload has no 'observations' key; "
            f"top-level keys were {sorted(payload) if isinstance(payload, dict) else type(payload)}"
        )

    contract = bundle.contract
    out: list[FredSeriesObservation] = []
    for row in payload["observations"]:
        raw_value = str(row.get("value", "")).strip()
        # FRED writes "." for a period the publisher suppressed or has not released.
        # It is an absence, and an absence is skipped -- never coerced to zero.
        if raw_value in {"", "."}:
            continue
        try:
            period_end = date.fromisoformat(str(row["date"]).strip())
            value = Decimal(raw_value)
            available_at = _instant(row["realtime_start"])
        except KeyError as exc:
            raise NormalizationError(
                f"FRED series {bundle.series_id} row {row!r} is missing {exc}; "
                "realtime_start is what makes a value point-in-time readable"
            ) from exc
        except (ValueError, InvalidOperation) as exc:
            raise NormalizationError(
                f"FRED series {bundle.series_id} row {row!r} is unparseable: {exc!r}"
            ) from exc

        superseded_raw = str(row.get("realtime_end", "")).strip()
        superseded_at = (
            None
            if superseded_raw in {"", "9999-12-31"}
            else _superseded_instant(superseded_raw)
        )
        out.append(
            FredSeriesObservation(
                series_id=bundle.series_id,
                domain=contract.domain,
                frequency=contract.frequency,
                unit=contract.unit,
                publisher_transform=contract.publisher_transform,
                period_end=period_end,
                value_numeric=value,
                available_at=available_at,
                superseded_at=superseded_at,
                parser_version=PARSER_VERSION,
                vintage_hash=_vintage_hash(
                    series_id=bundle.series_id,
                    period_end=period_end,
                    available_at=available_at,
                    unit=contract.unit,
                    value=value,
                ),
            )
        )
    return out


def observations_known_on(
    rows: list[FredSeriesObservation], *, as_of: datetime
) -> list[FredSeriesObservation]:
    """The values that were the published values at ``as_of``.

    A vintage is in force over ``[available_at, superseded_at)``.  Selecting on
    ``available_at <= as_of`` alone would return every restatement ever made, so the
    supersession bound is what keeps a later correction out of an earlier replay.
    """
    return [
        row
        for row in rows
        if row.available_at <= as_of
        and (row.superseded_at is None or as_of < row.superseded_at)
    ]


def _instant(raw: object) -> datetime:
    """FRED dates a vintage to the day; the day starts at midnight UTC."""
    return datetime.combine(
        date.fromisoformat(str(raw).strip()), datetime.min.time(), UTC
    )


def _superseded_instant(raw: object) -> datetime:
    """The instant a vintage stopped being current.

    FRED's ``realtime_end`` is the last day the value WAS current, inclusive.  A
    half-open window therefore closes at the start of the following day; closing it
    at the start of ``realtime_end`` itself erases the vintage for its whole final
    day, so a replay on exactly that date returns no value at all.
    """
    return _instant(raw) + timedelta(days=1)


def _vintage_hash(
    *,
    series_id: str,
    period_end: date,
    available_at: datetime,
    unit: str,
    value: Decimal,
) -> str:
    record = {
        "available_at": available_at.astimezone(UTC).isoformat(),
        "parser_version": PARSER_VERSION,
        "period_end": period_end.isoformat(),
        "series_id": series_id,
        "source": SOURCE,
        "unit": unit,
        "value": format(value.normalize(), "f"),
    }
    canonical = json.dumps(record, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(canonical).hexdigest()
