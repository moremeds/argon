"""Reading a stored macro domain state back at a requested instant.

Shared by the ``/api/macro/*`` and ``/api/rates/snapshot`` routers, which replay
against the same desk: one way to name the instant (``resolve_instant``) and one
compact summary of a stored state (``state_summary_fields``).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Any


class InvalidInstant(ValueError):
    """The request named its instant ambiguously. The API answers it as a 422 with
    this message as ``detail`` (``uw_scan.api.server`` registers the handler), so
    this module stays free of the web framework."""


#: A state older than this has not been recomputed since, which is a statement about our
#: scheduler and not about the publishers -- each factor carries its own freshness inside
#: ``confidence_reasons``.  Matched to the rates snapshot's own window so two surfaces
#: reading the same desk do not disagree about what "stale" means.
STATE_STALE_AFTER = timedelta(hours=36)


def state_summary_fields(
    row: dict[str, Any], *, requested_as_of: datetime
) -> dict[str, Any]:
    """The fields both the full state and the compact snapshot block share."""
    age = requested_as_of - row["as_of"]
    return {
        "domain": row["domain"],
        "as_of": row["as_of"],
        "computed_at": row["computed_at"],
        "engine_version": row["engine_version"],
        "state": row["state"],
        "direction": row["direction"],
        "confidence": row["confidence"],
        "freshness": "fresh" if age <= STATE_STALE_AFTER else "stale",
        # Negative when a caller replays a date the state predates by design; reported as
        # measured rather than clamped, so an odd number stays visible instead of
        # rounding to a reassuring zero.
        "age_hours": round(age.total_seconds() / 3600, 2),
        "velocity": row["velocity_jsonb"],
        "confidence_reasons": row["confidence_reasons_jsonb"],
        "contradictions": row["contradictions_jsonb"],
        "notes": row["notes_jsonb"],
    }


def resolve_instant(as_of: date | None, as_of_ts: datetime | None) -> datetime:
    """The instant a request is replaying, from the two ways of naming one.

    Public because the rates router replays against the same desk: the macro desk
    renders four ``/api/macro/*`` cards beside ``/api/rates/snapshot``, and a second
    copy of this would let one tab accept an ``as_of`` the other rejected -- or, worse,
    silently read a naive timestamp as UTC on one surface and refuse it on the other.
    """
    if as_of is not None and as_of_ts is not None:
        raise InvalidInstant("supply either as_of or as_of_ts, not both")
    if as_of_ts is not None:
        # A naive instant is a timezone guess, and the FOMC publishes at 14:00
        # ET -- guessing UTC moves the release four or five hours.
        if as_of_ts.tzinfo is None or as_of_ts.utcoffset() is None:
            raise InvalidInstant("as_of_ts must carry a UTC offset")
        return as_of_ts
    if as_of is not None:
        return datetime.combine(as_of, time.max, tzinfo=UTC)
    return datetime.now(UTC)
