"""Gold's declared inputs, and the manifest that proves what was read.

The three lenses are unchanged by this module.  What changes is what they can prove they
consumed.

**The defect this exists to close.**  ``reports/gold_posture.py`` pinned a four-entry
``inputs_used`` manifest -- ``DFII10``, ``GLD_CLOSE``, ``T5YIFR``, ``CPIAUCSL`` -- while
the orchestrator read ten sources and passed two more as deliberately empty.  A manifest
naming four of twelve is worse than none: it reads as a complete audit trail, and every
consumer downstream treats it as one.

**Why a registry and not a longer literal.**  The four-entry manifest was not written
wrong; it was written correct and then went stale as reads were added beside it.  A
hand-maintained list next to the reads it describes will desync again, and the second
time nobody will notice either.  So the reads and the manifest are generated from ONE
declaration: :data:`GOLD_INPUTS`.  Adding a source without declaring it is not possible
without also failing :func:`read_gold_inputs`, and a declared source that returns nothing
becomes an explicit omission rather than silence.

**What this manifest does NOT claim.**  It records the rows the orchestrator read,
which is not the same as the rows that were knowable at ``as_of``.  The gold flow tables
are queried by observation period and their ``as_of`` column is left unbounded, exactly
as before this change -- ``fetch_etf_flows_daily`` accepts an ``as_of_max`` the
orchestrator does not pass.  Bounding it would change what the three lenses see, which is
a lens change and not a provenance one, so it is recorded here rather than done quietly.
The tables are append-only, so the rows are at least immutable; they are not yet
replayable.

**An omission is evidence.**  ``fx`` and ``spx`` are passed to the lens functions as
empty lists today.  They are recorded with a reason, never as an absent key and never as
a fabricated id -- "we do not read this" and "this had no rows" are different facts, and
both differ from "this was never considered."

Design: ``docs/superpowers/specs/2026-08-12-usd-gold-state-design.md``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Literal

Lens = Literal["L1", "L2", "L3"]

#: Windows the orchestrator reads, kept here so the manifest reports the window that was
#: actually asked for rather than one a reader infers from the rows that came back.
_FLOW_WINDOW_DAYS = 400
_ETF_FLOW_WINDOW_DAYS = 45
_INVENTORY_WINDOW_DAYS = 60


@dataclass(frozen=True)
class GoldInput:
    """One declared input: what it is, who consumes it, and how it is read.

    ``read`` returning ``None`` marks an input the orchestrator does NOT read today --
    ``fx`` and ``spx`` are passed as empty lists to the lens functions. Declaring them
    with a reason is the difference between a known gap and an unexamined one.
    """

    key: str
    lens: tuple[Lens, ...]
    causal_role: str
    source: str
    #: Which column carries the observation period, because these tables disagree:
    #: ``obs_date``, ``obs_month`` and ``release_date`` all appear.
    period_field: str
    #: The warm-store table the read lands on. Declared so a test can check the one
    #: property that makes these rows quotable as evidence at all: every gold table
    #: keys on ``(..., as_of)`` and inserts ``DO NOTHING``, so a value read back is the
    #: value that was stored. Part A refused to source ``supply``/``positioning`` from
    #: the rates legacy tables for the opposite reason -- those update on conflict, and
    #: promoting one would launder a mutated number into the evidence store.
    table: str | None = None
    read: Callable[[Any, date], Sequence[Mapping[str, Any]]] | None = None
    not_read_reason: str | None = None
    #: A lens degrades without it, rather than being unavailable.
    required: bool = True

    def __post_init__(self) -> None:
        if (self.read is None) == (self.not_read_reason is None):
            raise ValueError(
                f"{self.key} must declare exactly one of read/not_read_reason: an input "
                "that is neither read nor explained is the gap this registry exists to "
                "make impossible"
            )


def _macro_daily(series_id: str) -> Callable[[Any, date], Sequence[Mapping[str, Any]]]:
    return lambda repo, as_of: repo.fetch_macro_series_daily(series_id, to_date=as_of)


def _macro_monthly(
    series_id: str,
) -> Callable[[Any, date], Sequence[Mapping[str, Any]]]:
    return lambda repo, as_of: repo.fetch_macro_series_monthly(
        series_id, to_month=date(as_of.year, as_of.month, 1)
    )


#: Every input the gold orchestrator consumes, declared once.
#:
#: The order is the order a reader should think in: price and its lenses, then structural
#: flow, then the valuation anchors. ``causal_role`` uses the shared macro vocabulary so a
#: gold input can be compared with a rates one without a translation table.
GOLD_INPUTS: tuple[GoldInput, ...] = (
    # --- price, read by every lens ---
    GoldInput(
        key="GLD_CLOSE",
        lens=("L1", "L2", "L3"),
        causal_role="decomposition_component",
        source="massive.com",
        period_field="obs_date",
        table="macro_series_daily",
        read=_macro_daily("GLD_CLOSE"),
    ),
    # --- Lens 2, regime-gated cyclical ---
    GoldInput(
        key="DFII10",
        lens=("L2",),
        causal_role="decomposition_component",
        source="fred",
        period_field="obs_date",
        table="macro_series_daily",
        read=_macro_daily("DFII10"),
    ),
    GoldInput(
        key="T5YIFR",
        lens=("L2",),
        causal_role="expectations_market",
        source="fred",
        period_field="obs_date",
        table="macro_series_daily",
        read=_macro_daily("T5YIFR"),
    ),
    GoldInput(
        key="CPIAUCSL",
        lens=("L2", "L3"),
        causal_role="realized",
        source="fred",
        period_field="obs_month",
        table="macro_series_monthly",
        read=_macro_monthly("CPIAUCSL"),
    ),
    # --- Lens 1, structural flow ---
    GoldInput(
        key="cb_gold_reserves_monthly",
        lens=("L1",),
        causal_role="positioning",
        source="wgc",
        period_field="obs_month",
        table="cb_gold_reserves_monthly",
        read=lambda repo, as_of: repo.fetch_cb_gold_reserves_monthly(
            from_month=as_of - timedelta(days=_FLOW_WINDOW_DAYS)
        ),
    ),
    GoldInput(
        key="etf_holdings_daily",
        lens=("L1",),
        causal_role="positioning",
        source="spdrgoldshares",
        period_field="obs_date",
        table="etf_holdings_daily",
        read=lambda repo, as_of: repo.fetch_etf_holdings_daily(
            "GLD", from_date=as_of - timedelta(days=_FLOW_WINDOW_DAYS)
        ),
    ),
    GoldInput(
        key="etf_flows_daily",
        lens=("L1",),
        causal_role="positioning",
        source="spdrgoldshares",
        period_field="obs_date",
        table="etf_flows_daily",
        read=lambda repo, as_of: repo.fetch_etf_flows_daily(
            "GLD",
            from_date=as_of - timedelta(days=_ETF_FLOW_WINDOW_DAYS),
            to_date=as_of,
        ),
    ),
    GoldInput(
        key="exchange_inventory_daily",
        lens=("L1",),
        causal_role="supply",
        source="comex",
        period_field="obs_date",
        table="exchange_inventory_daily",
        read=lambda repo, as_of: repo.fetch_exchange_inventory_daily(
            "COMEX", from_date=as_of - timedelta(days=_INVENTORY_WINDOW_DAYS)
        ),
    ),
    GoldInput(
        key="cot_gold_weekly",
        lens=("L1",),
        causal_role="positioning",
        source="cftc",
        period_field="release_date",
        table="cot_gold_weekly",
        read=lambda repo, as_of: repo.fetch_cot_gold_weekly(
            from_release_date=as_of - timedelta(days=_FLOW_WINDOW_DAYS),
            to_release_date=as_of,
        ),
    ),
    # --- Lens 3, valuation overlay ---
    GoldInput(
        key="M2SL",
        lens=("L3",),
        causal_role="decomposition_component",
        source="fred",
        period_field="obs_month",
        table="macro_series_monthly",
        read=_macro_monthly("M2SL"),
    ),
    # --- declared, and deliberately not read ---
    GoldInput(
        key="fx",
        lens=("L1",),
        causal_role="curve",
        source="none",
        period_field="obs_date",
        required=False,
        not_read_reason=(
            "compute_structural_posture is called with fx_rows=[]. No FX leg is ingested "
            "for the gold complex, so the structural lens sees no currency effect at all "
            "-- recorded because an empty list reaching a lens is indistinguishable in "
            "the output from a currency that did not move"
        ),
    ),
    GoldInput(
        key="spx",
        lens=("L3",),
        causal_role="curve",
        source="none",
        period_field="obs_date",
        required=False,
        not_read_reason=(
            "compute_valuation_overlay is called with spx_series=[]. The gold/equity "
            "ratio anchor is therefore never computed, and the overlay reports on the "
            "CPI and M2 anchors alone"
        ),
    ),
)


@dataclass(frozen=True)
class InputReading:
    """One declared input's rows plus what makes them auditable."""

    key: str
    rows: tuple[Mapping[str, Any], ...]
    latest_period: date | None
    latest_as_of: datetime | None
    omission_reason: str | None

    @property
    def present(self) -> bool:
        return bool(self.rows)


def read_gold_inputs(repo: Any, as_of: date) -> dict[str, InputReading]:
    """Read every declared input, recording an absence as a reason rather than a gap.

    A read that raises is NOT swallowed. A source whose query is broken must not be
    reported as a source that published nothing -- that is the same conflation the
    four-entry manifest made, one level down.
    """
    out: dict[str, InputReading] = {}
    for declared in GOLD_INPUTS:
        if declared.read is None:
            out[declared.key] = InputReading(
                key=declared.key,
                rows=(),
                latest_period=None,
                latest_as_of=None,
                omission_reason=declared.not_read_reason,
            )
            continue
        rows = tuple(declared.read(repo, as_of) or ())
        out[declared.key] = InputReading(
            key=declared.key,
            rows=rows,
            latest_period=_latest(rows, declared.period_field),
            latest_as_of=_latest_as_of(rows),
            omission_reason=(
                None
                if rows
                else (
                    f"no rows in {declared.source} for {declared.key} at or before "
                    f"as_of; the lens degrades rather than substituting a neighbour"
                )
            ),
        )
    return out


def evidence_manifest(readings: Mapping[str, InputReading]) -> dict[str, Any]:
    """The complete manifest: every declared input, present or explained.

    Every key in :data:`GOLD_INPUTS` appears. That is the invariant -- a reader can tell
    "this was not consulted" from "this had nothing to say" from "this is what it said",
    and no input is silently absent from the record.
    """
    missing = {item.key for item in GOLD_INPUTS} - set(readings)
    if missing:
        raise ValueError(
            f"{sorted(missing)} declared in GOLD_INPUTS but absent from the readings; "
            "the manifest must cover every declared input or it is a partial audit "
            "trail presenting as a complete one"
        )
    out: dict[str, Any] = {}
    for declared in GOLD_INPUTS:
        reading = readings[declared.key]
        out[declared.key] = {
            "lens": list(declared.lens),
            "causal_role": declared.causal_role,
            "source": declared.source,
            "table": declared.table,
            "required": declared.required,
            "row_count": len(reading.rows),
            "obs_date": (
                reading.latest_period.isoformat() if reading.latest_period else None
            ),
            "as_of": (
                reading.latest_as_of.isoformat() if reading.latest_as_of else None
            ),
            "omission_reason": reading.omission_reason,
        }
    return out


def _latest(rows: Sequence[Mapping[str, Any]], field: str) -> date | None:
    values = [row[field] for row in rows if row.get(field) is not None]
    return max(values) if values else None


def _latest_as_of(rows: Sequence[Mapping[str, Any]]) -> datetime | None:
    # Not every gold table carries an as_of; those that do are the point-in-time ones,
    # and the manifest reports it only where the publisher's own clock exists.
    values = [row["as_of"] for row in rows if row.get("as_of") is not None]
    return max(values) if values else None
