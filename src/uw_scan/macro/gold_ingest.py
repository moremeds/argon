"""Gold's own two series, promoted from the warm store into the evidence store.

**Why this module has to exist at all.**  The Gold Compass has read gold prices and ETF
tonnage for a long time, but it read them from ``macro_series_daily`` and
``etf_holdings_daily`` -- the WARM store, which carries no ``obs_id``.  A
``MacroDomainState`` whose evidence cannot be pointed at is refused at persist time by
design, so the gold domain could not produce a state no matter how good its engine was.
The schema was never the blocker: ``macro_observations`` has accepted
``domain = 'gold'`` since migration 115.  Only the ingest was missing.

**Two series and no more.**  Gold's Lens 2 also reads the real yield and the broad
dollar, and those are NOT ingested here -- they are owned by ``RATES_EVIDENCE`` and
``USD_EVIDENCE`` and gold points at the same stored rows.  Ingesting them again under a
second owner is precisely the double-count the design spec prohibits, and this module is
where it would happen.

**Availability follows R1.**  Neither publisher stamps a per-observation release instant:
massive answers a query and SPDR posts a file.  So ``published_at`` is NULL and
``available_at`` is our retrieval clock -- conservative in the only direction that
matters, because it never claims we could have known a price before we fetched it.  The
cost, stated plainly: history ingested today is not PIT-replayable before today.  That is
not a limitation this choice introduces, it is the true epistemic state of a row we first
saw this morning, and migration 119 can promote a verified instant later.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from uw_scan.macro_evidence import macro_artifact_content_identity
from uw_scan.models.macro import MacroSourceArtifact

DOMAIN = "gold"

GOLD_PRICE_SERIES = "GLD_CLOSE"
GOLD_PRICE_SOURCE = "massive.com"
GOLD_PRICE_PARSER_VERSION = "gold_price/1"
#: GLD closes, in dollars per share. The Compass's canonical gold-price series since the
#: retired FRED LBMA fix; keeping the same ``series_id`` is what lets the evidence store
#: and the warm store describe the same thing.
GOLD_PRICE_UNIT = "usd_per_share"

GOLD_FLOW_SERIES = "GLD_HOLDINGS_OZ"
GOLD_FLOW_SOURCE = "spdrgoldshares"
GOLD_FLOW_PARSER_VERSION = "gold_flow/1"
#: Troy ounces held by the trust. Ounces and never dollars: tonnage counted in ounces
#: rises only when metal actually enters the trust, so a rally cannot be read as
#: accumulation. A dollar-denominated holdings series would make Lens 1 a price series
#: wearing a flow label.
GOLD_FLOW_UNIT = "troy_oz"


@dataclass(frozen=True)
class GoldObservation:
    """One published gold value with the instant it became knowable."""

    series_id: str
    causal_role: str
    period_end: date
    value_numeric: Decimal
    unit: str
    available_at: datetime
    source: str
    parser_version: str


def gold_price_artifact(
    raw_bytes: bytes, *, source_url: str, retrieved_at: datetime
) -> MacroSourceArtifact:
    content_hash, content_length = macro_artifact_content_identity(raw_bytes=raw_bytes)
    return MacroSourceArtifact(
        source=GOLD_PRICE_SOURCE,
        source_kind="entitled_provider",
        source_record_id=f"{GOLD_PRICE_SOURCE}:gld-daily-ohlc",
        source_url=source_url,
        # A query result, not a dated release: these bytes became available when we asked.
        published_at=None,
        available_at=retrieved_at,
        retrieved_at=retrieved_at,
        last_seen_at=retrieved_at,
        content_hash=content_hash,
        parser_version=GOLD_PRICE_PARSER_VERSION,
        quality_status="valid",
        # ``already_entitled`` and not ``paid_authorized``: the massive subscription is
        # bought for the OHLC lane and this call rides it, so the marginal cost of gold's
        # evidence is zero. The distinction is what the cost class is FOR -- it lets a
        # reader see which evidence would disappear if a budget were cut.
        cost_class="already_entitled",
        media_type="application/json",
        content_length=content_length,
        # The payload carries a bar history, so it reports many periods rather than
        # being one dated release.
        vintage_bearing=True,
        raw_bytes=raw_bytes,
    )


def gold_flow_artifact(
    raw_bytes: bytes, *, source_url: str, media_type: str, retrieved_at: datetime
) -> MacroSourceArtifact:
    content_hash, content_length = macro_artifact_content_identity(raw_bytes=raw_bytes)
    return MacroSourceArtifact(
        source=GOLD_FLOW_SOURCE,
        source_kind="official",
        source_record_id=f"{GOLD_FLOW_SOURCE}:gld-holdings-archive",
        source_url=source_url,
        published_at=None,
        available_at=retrieved_at,
        retrieved_at=retrieved_at,
        last_seen_at=retrieved_at,
        content_hash=content_hash,
        parser_version=GOLD_FLOW_PARSER_VERSION,
        quality_status="valid",
        cost_class="free_official",
        # SPDR serves the same archive as CSV or XLSX depending on the day; the caller
        # reports which arrived rather than this module assuming one.
        media_type=media_type,
        content_length=content_length,
        vintage_bearing=True,
        raw_bytes=raw_bytes,
    )


def price_observations(
    bars: Sequence[Any], *, retrieved_at: datetime
) -> list[GoldObservation]:
    """One observation per daily bar close.

    A bar with a non-positive close is DROPPED rather than stored: gold has never traded
    at or below zero, so such a row is a parse failure or a vendor placeholder, and one
    of those inside a percent-change window silently produces an enormous move.
    """
    out: list[GoldObservation] = []
    for bar in bars:
        close = getattr(bar, "close", None)
        bar_date = getattr(bar, "date", None)
        if close is None or bar_date is None:
            continue
        value = Decimal(str(close))
        if value <= 0:
            continue
        out.append(
            GoldObservation(
                series_id=GOLD_PRICE_SERIES,
                causal_role="decomposition_component",
                period_end=bar_date,
                value_numeric=value,
                unit=GOLD_PRICE_UNIT,
                available_at=retrieved_at,
                source=GOLD_PRICE_SOURCE,
                parser_version=GOLD_PRICE_PARSER_VERSION,
            )
        )
    return out


def flow_observations(
    rows: Sequence[Any], *, retrieved_at: datetime
) -> list[GoldObservation]:
    """One observation per published holdings print, in troy ounces."""
    out: list[GoldObservation] = []
    for row in rows:
        holdings = getattr(row, "holdings_oz", None)
        obs_date = getattr(row, "obs_date", None)
        if holdings is None or obs_date is None:
            continue
        value = Decimal(str(holdings))
        if value <= 0:
            continue
        out.append(
            GoldObservation(
                series_id=GOLD_FLOW_SERIES,
                causal_role="positioning",
                period_end=obs_date,
                value_numeric=value,
                unit=GOLD_FLOW_UNIT,
                available_at=retrieved_at,
                source=GOLD_FLOW_SOURCE,
                parser_version=GOLD_FLOW_PARSER_VERSION,
            )
        )
    return out


def observation_row(
    observation: GoldObservation,
    *,
    artifact_id: int,
    artifact: MacroSourceArtifact,
    available_at: datetime | None = None,
) -> dict[str, Any]:
    """The row shape the observation writer takes.

    ``available_at`` overrides the observation's own when the caller knows the STORED
    artifact's retrieval instant -- which differs from this run's clock whenever the
    payload deduped to one we already had. The store enforces that an observation cannot
    postdate the artifact carrying it, so this is what makes a re-run idempotent instead
    of a hard failure.
    """
    return {
        "artifact_id": artifact_id,
        "domain": DOMAIN,
        "series_id": observation.series_id,
        "period_end": observation.period_end,
        "frequency": "daily",
        "unit": observation.unit,
        "value_numeric": observation.value_numeric,
        "source": artifact.source,
        "source_record_id": artifact.source_record_id,
        # Always NULL, per R1. Neither publisher stamps a per-observation release
        # instant, and deriving one by rule would be indistinguishable in the schema
        # from an observed one.
        "published_at": None,
        "available_at": available_at or observation.available_at,
        "parser_version": observation.parser_version,
        "quality_status": "valid",
        "cost_class": artifact.cost_class,
    }
