"""三类买卖点/背离/区间套 — field-for-field port of web/lib/chanlun.ts.

Algorithm source: docs/superpowers/specs/2026-07-14-chanlun-py-port-contract.md
(port contract) §C.9-C.11, §C.13, cited per function below. Pure compute, no I/O.

Numeric semantics (port contract §E): no epsilon/tolerance anywhere — every
comparison operates on raw floats, no fuzzing. `DIVERGENCE_RATE` gates are
strict `<`.
"""

from __future__ import annotations

from typing import Callable

from uw_scan.chanlun.core import DIVERGENCE_RATE
from uw_scan.chanlun.types import (
    BuySellPoint,
    ChanlunResult,
    DivergenceMark,
    Leg,
    Pivot,
    VertexPt,
)

LegArea = Callable[[Leg], float]


def mark_points(
    pts: list[VertexPt],
    legs: list[Leg],
    pivots: list[Pivot],
    leg_area: LegArea,
) -> list[BuySellPoint]:
    """三类买卖点 (3B/3S + pivot-anchored 1B/1S/2B/2S). port-contract §C.9, chanlun.ts:296-356.

    3B/3S: BOTH independent guards are evaluated (not if/else) — a deliberate
    defensive "direction guard", not textbook derivation. 1B/1S/2B/2S:
    `connect`/`exit` are the legs immediately BEFORE each pivot's exit leg
    (`legs[exitLeg - 1]`), never the exit leg itself. `retest = pts[exit.b+2]`
    is a fixed +2 offset, not a scan — out-of-range silently skips 2B/2S.
    `DIVERGENCE_RATE` gate is strict `<`. Final sort by `time` (plain string
    sort is safe for this fixed-width ISO format — port-contract §G.1).
    """
    points: list[BuySellPoint] = []

    def mark(kind: str, v_idx: int) -> None:
        v = pts[v_idx]
        points.append(
            BuySellPoint(time=v.time, price=v.price, kind=kind, confirmed=v.confirmed)
        )

    for k, p in enumerate(pivots):
        if p.exitLeg is not None:
            exit_l = legs[p.exitLeg]
            if p.exitUp and not exit_l.up:
                mark("3B", exit_l.b)
            if (not p.exitUp) and exit_l.up:
                mark("3S", exit_l.b)

        prev = pivots[k - 1] if k - 1 >= 0 else None
        if prev is None or prev.exitLeg is None or p.exitLeg is None:
            continue
        connect = legs[prev.exitLeg - 1]
        exit_leg = legs[p.exitLeg - 1]
        rising = p.zd > prev.zg and connect.up and exit_leg.up
        falling = p.zg < prev.zd and (not connect.up) and (not exit_leg.up)
        new_extreme = (
            pts[exit_leg.b].price > pts[connect.b].price
            if rising
            else pts[exit_leg.b].price < pts[connect.b].price
        )
        if (
            (rising or falling)
            and new_extreme
            and leg_area(exit_leg) < DIVERGENCE_RATE * leg_area(connect)
        ):
            first = "1S" if rising else "1B"
            mark(first, exit_leg.b)
            retest_idx = exit_leg.b + 2
            retest = pts[retest_idx] if 0 <= retest_idx < len(pts) else None
            if retest is not None and retest.kind == pts[exit_leg.b].kind:
                if first == "1B" and retest.price > pts[exit_leg.b].price:
                    mark("2B", retest_idx)
                if first == "1S" and retest.price < pts[exit_leg.b].price:
                    mark("2S", retest_idx)

    points.sort(key=lambda pt: pt.time)
    return points


def mark_divergences(
    pts: list[VertexPt],
    legs: list[Leg],
    leg_area: LegArea,
) -> list[DivergenceMark]:
    """顶背离/底背离 on 笔, annotation-only. port-contract §C.10, chanlun.ts:362-385.

    `legs[i]` vs `legs[i+2]` (always same-direction — directions alternate
    every leg). No final sort — natural iteration order is already
    chronological. Decoupled from `mark_points`'s pivot-anchored 1B/1S check
    (the two are not required to agree).
    """
    out: list[DivergenceMark] = []
    for i in range(len(legs) - 2):
        a = legs[i]
        b = legs[i + 2]
        extended = (
            pts[b.b].price > pts[a.b].price if b.up else pts[b.b].price < pts[a.b].price
        )
        if extended and leg_area(b) < DIVERGENCE_RATE * leg_area(a):
            v = pts[b.b]
            out.append(
                DivergenceMark(
                    time=v.time, price=v.price, kind=v.kind, confirmed=v.confirmed
                )
            )
    return out


def mark_resonance(
    points: list[BuySellPoint],
    weekly: ChanlunResult,
    last_bar_time: str,
) -> list[BuySellPoint]:
    """区间套 (multi-timeframe resonance). port-contract §C.13, chanlun.ts:499-526.

    Returns a NEW list, never mutates input. Vertex lookup is the first exact
    `(time, price)` match (`-1` sentinel on no match, port-contract §G.7).
    `to` falls back to `last_bar_time` when there is no following vertex.
    Only `p.confirmed` points are eligible; non-resonant points are returned
    UNCHANGED — `resonant` stays `None`, never an explicit `False`
    (port-contract §G.10).
    """

    def side(kind: str) -> str:
        return "B" if kind.endswith("B") else "S"

    windows: list[tuple[str, str, str]] = []  # (side, from, to)
    for q in weekly.points:
        if not q.confirmed:
            continue
        vi = next(
            (
                i
                for i, v in enumerate(weekly.vertices)
                if v.time == q.time and v.price == q.price
            ),
            -1,
        )
        to = (
            weekly.vertices[vi + 1].time
            if vi >= 0 and vi + 1 < len(weekly.vertices)
            else last_bar_time
        )
        windows.append((side(q.kind), q.time, to))

    if not windows:
        return list(points)

    out: list[BuySellPoint] = []
    for p in points:
        p_side = side(p.kind)
        hit = p.confirmed and any(
            w_side == p_side and w_from <= p.time <= w_to
            for w_side, w_from, w_to in windows
        )
        if hit:
            out.append(
                BuySellPoint(
                    time=p.time,
                    price=p.price,
                    kind=p.kind,
                    confirmed=p.confirmed,
                    resonant=True,
                )
            )
        else:
            out.append(p)
    return out
