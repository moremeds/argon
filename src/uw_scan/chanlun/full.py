"""v1/v2 top-level orchestration — field-for-field port of web/lib/chanlun.ts.

Algorithm source: docs/superpowers/specs/2026-07-14-chanlun-py-port-contract.md
(port contract) §C.5, §C.14, §C.15, cited below. `compute_chanlun` is "v1"
(笔/中枢/买卖点/背离); `compute_chanlun_full` is "v2", adding 线段/segments +
weekly 区间套 resonance on top of v1.
"""

from __future__ import annotations

import math

from uw_scan.chanlun.core import (
    MIN_BARS,
    build_endpoints,
    build_legs,
    build_pivots,
    find_fractals,
    macd_hist,
    merge_inclusions,
    merge_overlapping_zhongshus,
    pivots_to_zhongshus,
    resample_weekly,
)
from uw_scan.chanlun.points import mark_divergences, mark_points, mark_resonance
from uw_scan.chanlun.segments import build_segments
from uw_scan.chanlun.types import (
    BiVertex,
    ChanlunBar,
    ChanlunFullResult,
    ChanlunResult,
    Fractal,
    Leg,
    VertexPt,
)


def _empty_result() -> ChanlunResult:
    return ChanlunResult(vertices=[], zhongshus=[], points=[], divergences=[])


def compute_chanlun(bars: list[ChanlunBar]) -> ChanlunResult:
    """v1 pipeline: 笔/中枢/买卖点/背离. port-contract §C.5, §C.14, chanlun.ts:394-468.

    Input guard (port-contract §G.5): every `bar.close` must be finite —
    real market data always is; this is a deliberate fail-fast policy, not a
    reproduction of the JS `null - null === 0` coercion the reference never
    actually exercises.

    Provisional-tail construction (§C.5) after `buildEndpoints`:
    - Step (a): extend the tail while the running same-direction extreme
      (`extSame`, sliding base — `is None` guard, not `or`) strictly beats it.
    - Step (b): grow a forming counter-leg past the (possibly replaced) tail,
      non-strict `<=`/`>=`, base slides.
    `confirmedCount = len(eps) - 1` is captured BEFORE either mutation;
    `confirmed = i < confirmedCount` is applied to the FINAL `eps` index.
    """
    if any(not math.isfinite(b.close) for b in bars):
        raise ValueError("compute_chanlun: all bar.close values must be finite")

    if len(bars) < MIN_BARS:
        return _empty_result()

    m = merge_inclusions(bars)
    eps = build_endpoints(find_fractals(m))
    if len(eps) == 0:
        return _empty_result()

    confirmed_count = len(eps) - 1
    tail = eps[-1]
    ext_same: Fractal | None = None
    for j in range(tail.mIdx + 1, len(m)):
        base = ext_same if ext_same is not None else tail
        beyond = m[j].high > base.price if tail.kind == "top" else m[j].low < base.price
        if beyond:
            ext_same = (
                Fractal(kind="top", mIdx=j, rawIdx=m[j].hiIdx, price=m[j].high)
                if tail.kind == "top"
                else Fractal(kind="bottom", mIdx=j, rawIdx=m[j].loIdx, price=m[j].low)
            )
    if ext_same is not None:
        eps[-1] = ext_same

    anchor = eps[-1]
    forming: Fractal | None = None
    for j in range(anchor.mIdx + 1, len(m)):
        better = (
            (forming is None or m[j].low <= forming.price)
            if anchor.kind == "top"
            else (forming is None or m[j].high >= forming.price)
        )
        if better:
            forming = (
                Fractal(kind="bottom", mIdx=j, rawIdx=m[j].loIdx, price=m[j].low)
                if anchor.kind == "top"
                else Fractal(kind="top", mIdx=j, rawIdx=m[j].hiIdx, price=m[j].high)
            )
    if forming is not None:
        eps.append(forming)

    vertices = [
        BiVertex(
            time=bars[f.rawIdx].time,
            price=f.price,
            kind=f.kind,
            confirmed=i < confirmed_count,
        )
        for i, f in enumerate(eps)
    ]
    pts = [
        VertexPt(
            time=bars[f.rawIdx].time,
            price=f.price,
            kind=f.kind,
            rawIdx=f.rawIdx,
            confirmed=i < confirmed_count,
        )
        for i, f in enumerate(eps)
    ]
    legs = build_legs(pts)
    pivots = build_pivots(legs)
    zhongshus = pivots_to_zhongshus(pivots, legs, pts)

    hist = macd_hist([b.close for b in bars])

    def leg_area(leg: Leg) -> float:
        return sum(abs(hist[r]) for r in range(leg.rawA + 1, leg.rawB + 1))

    points = mark_points(pts, legs, pivots, leg_area)
    divergences = mark_divergences(pts, legs, leg_area)

    return ChanlunResult(
        vertices=vertices, zhongshus=zhongshus, points=points, divergences=divergences
    )


def compute_chanlun_full(bars: list[ChanlunBar]) -> ChanlunFullResult:
    """v2 pipeline: v1 + 线段/segments + weekly 区间套 resonance.

    port-contract §C.15, chanlun.ts:537-574. `hist`/`leg_area` are recomputed
    here (not shared with `compute_chanlun`'s internal closure, §C.11) because
    segment legs span different raw-bar ranges than stroke legs. `points` is
    overridden with the resonance-flagged set; `zhongshus` is overridden with
    the merged/upgraded set; `divergences` and `vertices` pass through
    unchanged from `daily`. `segZhongshus`/`segPoints` are NOT merged/resonance
    -flagged — only the daily-level outputs get those treatments.
    """
    daily = compute_chanlun(bars)
    seg_vertices = build_segments(daily.vertices)
    idx_by_time = {b.time: i for i, b in enumerate(bars)}
    seg_pts = [
        VertexPt(
            time=v.time,
            price=v.price,
            kind=v.kind,
            rawIdx=idx_by_time.get(v.time, 0),
            confirmed=v.confirmed,
        )
        for v in seg_vertices
    ]

    hist = macd_hist([b.close for b in bars])

    def leg_area(leg: Leg) -> float:
        return sum(abs(hist[r]) for r in range(leg.rawA + 1, leg.rawB + 1))

    seg_legs = build_legs(seg_pts)
    seg_pivots = build_pivots(seg_legs)

    weekly = compute_chanlun(resample_weekly(bars))
    points = mark_resonance(daily.points, weekly, bars[-1].time if bars else "")

    return ChanlunFullResult(
        vertices=daily.vertices,
        zhongshus=merge_overlapping_zhongshus(daily.zhongshus),
        points=points,
        divergences=daily.divergences,
        segVertices=seg_vertices,
        segZhongshus=pivots_to_zhongshus(seg_pivots, seg_legs, seg_pts),
        segPoints=mark_points(seg_pts, seg_legs, seg_pivots, leg_area),
    )
