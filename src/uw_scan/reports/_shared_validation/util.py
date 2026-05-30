"""Tiny utilities shared across validation and markdown rendering."""

from __future__ import annotations

from datetime import datetime, timezone


def _iso_z(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
