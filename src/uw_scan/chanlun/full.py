"""v1 top-level orchestration — field-for-field port of web/lib/chanlun.ts.

Algorithm source: docs/superpowers/specs/2026-07-14-chanlun-py-port-contract.md
(port contract) §C.5, §C.14, cited below. `compute_chanlun_full` (v2, adding
线段/segments + resonance) is added in Task 5 — this module holds
`compute_chanlun` ("v1": 笔/中枢/买卖点/背离) only.
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
    pivots_to_zhongshus,
)
from uw_scan.chanlun.points import mark_divergences, mark_points
from uw_scan.chanlun.types import (
    BiVertex,
    ChanlunBar,
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
