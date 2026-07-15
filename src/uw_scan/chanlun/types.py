"""Stdlib dataclasses mirroring the TS chanlun types (web/lib/chanlun.ts).

Field-for-field port of the TS type inventory — see
docs/superpowers/specs/2026-07-14-chanlun-py-port-contract.md §A. Plain
mutable dataclasses (not frozen): `merge_inclusions` and
`merge_overlapping_zhongshus` mutate the "last" record in place, mirroring
the TS `last.high = ...` in-place mutation style.

Segment types (SegVertex, SegStats, Stroke, Elem) are added in Task 4 below.
ChanlunFullResult is added in Task 5, not here.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ChanlunBar:
    """One daily OHLC bar. port-contract §A, chanlun.ts:15-20.

    Exactly these four fields, NO `open` — the compute pipeline never reads
    it; raw `open` values stay in the caller's raw bar dicts.
    """

    time: str
    high: float
    low: float
    close: float


@dataclass
class MergedK:
    """One inclusion-merged candle. port-contract §A, chanlun.ts:22-27."""

    high: float
    low: float
    hiIdx: int
    loIdx: int


@dataclass
class Fractal:
    """A raw (pre-alternation) fractal candidate. port-contract §A, chanlun.ts:29-34."""

    kind: str  # "top" | "bottom"
    mIdx: int
    rawIdx: int
    price: float


@dataclass
class BiVertex:
    """A confirmed-alternating stroke endpoint (public output). port-contract §A, chanlun.ts:36-41."""

    time: str
    price: float
    kind: str  # "top" | "bottom"
    confirmed: bool


@dataclass
class Zhongshu:
    """A pivot zone. port-contract §A, chanlun.ts:43-50."""

    start: str
    end: str
    zg: float
    zd: float
    confirmed: bool
    level: int | None = None


@dataclass
class BuySellPoint:
    """A three-class buy/sell point. port-contract §A, chanlun.ts:54-60."""

    time: str
    price: float
    kind: str  # "1B" | "2B" | "3B" | "1S" | "2S" | "3S"
    confirmed: bool
    resonant: bool | None = None


@dataclass
class DivergenceMark:
    """A 顶背离/底背离 annotation. port-contract §A, chanlun.ts:64-69."""

    time: str
    price: float
    kind: str  # "top" | "bottom"
    confirmed: bool


@dataclass
class VertexPt:
    """Internal working vertex threaded through legs/pivots/points.

    Superset of BiVertex; carries rawIdx forward for MACD-area lookups.
    port-contract §A, chanlun.ts:187-193.
    """

    time: str
    price: float
    kind: str  # "top" | "bottom"
    rawIdx: int
    confirmed: bool


@dataclass
class Leg:
    """One stroke (or segment) expressed as a vertex-to-vertex leg. port-contract §A, chanlun.ts:195-203."""

    hi: float
    lo: float
    up: bool
    a: int
    b: int
    rawA: int
    rawB: int


@dataclass
class Pivot:
    """One pivot zone expressed over leg indices (pre-Zhongshu projection). port-contract §A, chanlun.ts:205-212."""

    firstLeg: int
    lastLeg: int
    exitLeg: int | None
    exitUp: bool
    zg: float
    zd: float


@dataclass
class ChanlunResult:
    """computeChanlun's return type. port-contract §A, chanlun.ts:71-76."""

    vertices: list[BiVertex]
    zhongshus: list[Zhongshu]
    points: list[BuySellPoint]
    divergences: list[DivergenceMark]


@dataclass
class SegVertex:
    """buildSegments' public output — same shape/contract as BiVertex.

    port-contract §A, chanlunSeg.ts:11-16.
    """

    time: str
    price: float
    kind: str  # "top" | "bottom"
    confirmed: bool


@dataclass
class SegStats:
    """Optional diagnostic counters, mutated in place if passed. port-contract §A, chanlunSeg.ts:18-22."""

    case1: int = 0
    case2Confirmed: int = 0
    case2Provisional: int = 0


@dataclass
class Stroke:
    """One 笔 recast as a segment-building primitive. port-contract §A, chanlunSeg.ts:24-30."""

    idx: int
    up: bool
    hi: float
    lo: float
    sure: bool  # both endpoint vertices confirmed


@dataclass
class Elem:
    """One feature-sequence element (chan.py CEigen). port-contract §A, chanlunSeg.ts:37-46."""

    hi: float
    lo: float
    up: bool  # MERGE direction, fixed once the element is created (not per-stroke)
    strokes: list[int]  # stroke indices folded into this element, in feed order
    hiStroke: int  # index of the stroke that currently carries the element's hi
    loStroke: int  # index of the stroke that currently carries the element's lo
    lastHi: float  # most-recently-folded stroke's own hi (chan.py actual_break state)
    lastLo: float
