"""Chanlun Phase B lifecycle API contract."""

from __future__ import annotations

from datetime import date, datetime

from uw_scan.models._base import _preserve_public_module, _UwBase


class ChanlunLifecycleMark(_UwBase):
    """Current lifecycle state of one daily chanlun mark (mark_id + state)."""

    category: str
    kind: str
    extreme_date: date
    extreme_price: float
    state: str
    reason: str | None = None
    first_entered_at: datetime
    as_of: date


class ChanlunLifecycleResponse(_UwBase):
    """Current state of every recorded mark for one ticker, excluding marks
    whose current state is invalidated/stale (spec §API). Breach, superseded,
    and split_boundary invalidations are included."""

    ticker: str
    marks: list[ChanlunLifecycleMark]


_preserve_public_module(ChanlunLifecycleMark, ChanlunLifecycleResponse)
