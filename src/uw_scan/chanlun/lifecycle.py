"""Pure lifecycle state machine + S1 sub-level confirmation predicate.

No I/O — stdlib only (dataclasses, math, datetime, zoneinfo, bisect). Design:
docs/superpowers/specs/2026-07-14-chanlun-phase-b-sublevel-confirm-design.md
(§Lifecycle state machine, §Confirm rule S1). Task 9's nightly job feeds this
module bars and persists its verdicts through storage/chanlun_signal_repository.py.
"""

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from uw_scan.chanlun.full import compute_chanlun
from uw_scan.chanlun.types import BiVertex, ChanlunBar, ChanlunFullResult

LN_SPLIT_THRESHOLD = math.log(1.5)
DEFAULT_STALE_SESSIONS = 20
# The four categories evaluated by the walk-forward sub-level probe
# (docs/research/2026-07-14-chanlun-signal-lifecycle/phaseb_probe/summary.md).
# ALL FOUR FAILED the survival gate on 2026-07-15 (~8-17% actual survival vs
# >=70% required, both ticker-halves) -- this is NOT a shipped default and is
# imported nowhere. `Settings.chanlun_promotable_categories` (empty string by
# design) is the only source of truth for what the nightly job promotes.
CANDIDATE_CATEGORIES = frozenset({"vertex", "divergence", "3B", "3S"})

_ET = ZoneInfo("America/New_York")


@dataclass
class Mark:
    """One lifecycle-tracked chanlun mark (vertex, divergence, or point).

    mark_id (spec §Lifecycle state machine) = (ticker, category, kind,
    extreme_date, extreme_price) — the ticker is threaded by the caller
    (Task 9), not carried here.
    """

    category: str  # "vertex" | "divergence" | "point"
    kind: str  # "top"/"bottom" for vertex/divergence; 1B/1S/2B/2S/3B/3S for point
    extreme_date: date
    extreme_price: float
    is_native_confirmed: bool


def derive_marks(full: ChanlunFullResult, bars: list[ChanlunBar]) -> list[Mark]:
    """Flatten a ChanlunFullResult into lifecycle Marks (vertices, divergences, points)."""
    marks: list[Mark] = []
    for v in full.vertices:
        marks.append(
            Mark(
                category="vertex",
                kind=v.kind,
                extreme_date=date.fromisoformat(v.time[:10]),
                extreme_price=v.price,
                is_native_confirmed=v.confirmed,
            )
        )
    for d in full.divergences:
        marks.append(
            Mark(
                category="divergence",
                kind=d.kind,
                extreme_date=date.fromisoformat(d.time[:10]),
                extreme_price=d.price,
                is_native_confirmed=d.confirmed,
            )
        )
    for p in full.points:
        marks.append(
            Mark(
                category="point",
                kind=p.kind,
                extreme_date=date.fromisoformat(p.time[:10]),
                extreme_price=p.price,
                is_native_confirmed=p.confirmed,
            )
        )
    return marks


def promotable_key(category: str, kind: str) -> str:
    """The token used against `chanlun_promotable_categories` — `category` for
    vertex/divergence, `kind` for point (so tokens are vertex,divergence,1B,1S,2B,2S,3B,3S)."""
    return kind if category == "point" else category


def is_promotable(category: str, kind: str, promotable: frozenset[str]) -> bool:
    return promotable_key(category, kind) in promotable


def mark_side(kind: str) -> str:
    """The price side of a mark kind: top/bottom pass through; point kinds map
    by suffix (1B/2B/3B -> bottom, 1S/2S/3S -> top)."""
    if kind in ("top", "bottom"):
        return kind
    if kind.endswith("B"):
        return "bottom"
    if kind.endswith("S"):
        return "top"
    raise ValueError(f"mark_side: unrecognized kind {kind!r}")


def find_split_boundaries(daily_bars: list[dict]) -> set[date]:
    """Dates `d` where |ln(open_d / close_{d-1})| > LN_SPLIT_THRESHOLD.

    Skips a pair if either open/close is missing or non-positive. Raw apex
    dicts carry a FULL UTC datetime string in `time` — MUST slice [:10]
    before date.fromisoformat (apex contract §2a); an unsliced implementation
    raises ValueError on real ticker data.
    """
    boundaries: set[date] = set()
    prev_close: float | None = None
    for b in daily_bars:
        d = date.fromisoformat(b["time"][:10])
        open_ = b.get("open")
        close = b.get("close")
        if (
            prev_close is not None
            and open_ is not None
            and open_ > 0
            and prev_close > 0
        ):
            if abs(math.log(open_ / prev_close)) > LN_SPLIT_THRESHOLD:
                boundaries.add(d)
        if close is not None and close > 0:
            prev_close = close
        else:
            prev_close = None
    return boundaries


def crosses_split_boundary(
    mark: Mark, anchor_start: date, boundaries: set[date]
) -> bool:
    """Any boundary date >= W's start (conservative)."""
    return any(anchor_start <= b for b in boundaries)


def session_et_date(ts: str) -> date:
    """The ET session date of a bar timestamp.

    Post-market 30m bars at/after 20:00 ET land on the NEXT UTC calendar
    date, so a naive UTC-date slice silently false-negates the S1 session
    conjunct on late after-hours anchor bars — always compare ET dates.
    """
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is not None:
        return dt.astimezone(_ET).date()
    return dt.date()


def anchor_window(
    mark: Mark, daily_vertices: list[BiVertex], session_dates: list[date]
) -> date:
    """Start date of W: the latest CONFIRMED daily vertex of the OPPOSITE side
    strictly before mark.extreme_date; fallback = 40 SESSIONS back (not
    calendar days) via bisect over session_dates.
    """
    opposite = "top" if mark_side(mark.kind) == "bottom" else "bottom"
    candidates = [
        date.fromisoformat(v.time[:10])
        for v in daily_vertices
        if v.confirmed
        and v.kind == opposite
        and date.fromisoformat(v.time[:10]) < mark.extreme_date
    ]
    if candidates:
        return max(candidates)
    idx = bisect.bisect_left(session_dates, mark.extreme_date)
    return session_dates[max(0, idx - 40)]


def s1_confirmed(
    mark: Mark,
    bars_30m: list[ChanlunBar],
    *,
    tol: float,
    require_divergence: bool = False,  # S2 hook — unused in v1
) -> tuple[bool, dict]:
    """S1 predicate (spec §Confirm rule S1). `bars_30m` is ALREADY windowed to
    the anchor window W by the caller. Returns (True, v30-anchor-info) on the
    first vertex satisfying all four conjuncts, else (False, {})."""
    if not bars_30m:
        return False, {}
    side = mark_side(mark.kind)  # bottom for bottom/1B/2B/3B; top for the mirror
    result = compute_chanlun(bars_30m)
    for v30 in result.vertices:
        if not v30.confirmed:
            continue  # conjunct 1 — the 30m stroke off v30 earned its opposite endpoint
        if v30.kind != side:
            continue  # conjunct 2 — same side as the daily mark
        if abs(v30.price - mark.extreme_price) > tol:
            continue  # conjunct 3a — exact-extreme anchor (tol=0.0 default; config escape hatch)
        if session_et_date(v30.time) != mark.extreme_date:
            continue  # conjunct 3b — v30's bar sits in the daily extreme's ET session
        # Conjunct 4 — v30 must remain the extreme of W on its side. "After" is
        # b.time > v30.time (uniform ISO-8601 strings -> lexicographic ==
        # chronological). bottom: a later low BELOW v30.price kills the match;
        # top: a later high ABOVE it.
        later = [b for b in bars_30m if b.time > v30.time]
        if side == "bottom" and any(b.low < v30.price for b in later):
            continue
        if side == "top" and any(b.high > v30.price for b in later):
            continue
        return True, {
            "v30_time": v30.time,
            "v30_price": v30.price,
            "v30_kind": v30.kind,
        }
    return False, {}


def breached(mark: Mark, later_daily_bars: list[dict]) -> bool:
    """For bottom-side kinds: any later daily low < extreme_price; for top-side:
    any later daily high > extreme_price. `later` bars are pre-filtered by the caller
    (dicts here carry only `low`/`high`, filtering by date is the caller's job per the
    brief's helper tests which pass already-later bars)."""
    side = mark_side(mark.kind)
    if side == "bottom":
        return any(b["low"] < mark.extreme_price for b in later_daily_bars)
    return any(b["high"] > mark.extreme_price for b in later_daily_bars)


def is_stale(
    mark: Mark, last_session: date, stale_sessions: int, session_dates: list[date]
) -> bool:
    """Count of session dates strictly after mark.extreme_date up to last_session
    exceeds stale_sessions."""
    count = sum(1 for d in session_dates if mark.extreme_date < d <= last_session)
    return count > stale_sessions


def evaluate_mark(
    *,
    mark: Mark,
    split_crossed: bool,
    breach: bool,
    s1_ok: bool,
    promotable: bool,
    stale: bool,
) -> tuple[str, str | None]:
    """Decision table (precedence top-to-bottom): split > native > breach >
    stale > S1 > pending. The "superseded" reason is assigned by the JOB
    (Task 9), not here — evaluate_mark only sees marks present in the recompute.
    """
    if split_crossed:
        return "invalidated", "split_boundary"
    if mark.is_native_confirmed:
        return "confirmed_native", None
    if breach:
        return "invalidated", "breach"
    if stale:
        return "invalidated", "stale"
    if promotable and s1_ok:
        return "confirmed_sublevel", None
    return "pending", None
