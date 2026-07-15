"""Stroke-level chanlun pipeline — field-for-field port of web/lib/chanlun.ts.

Algorithm source: docs/superpowers/specs/2026-07-14-chanlun-py-port-contract.md
(port contract) §C.1-C.8, C.12, cited per function below. Pure compute, no I/O.

Numeric semantics (port contract §E): no epsilon/tolerance anywhere — every
comparison operates on raw floats, no fuzzing. Tie-break rules vary by
function and must not be unified or "improved."
"""

from __future__ import annotations

from uw_scan.chanlun.types import (
    ChanlunBar,
    Fractal,
    Leg,
    MergedK,
    Pivot,
    VertexPt,
    Zhongshu,
)

# 新笔-style stroke rule: fractal midpoints >=4 merged candles apart.
# port-contract §B, chanlun.ts:82.
MIN_VERTEX_GAP = 4
# chan.py default: leg-2 must be <=90% of leg-1's MACD area to flag 背驰.
# port-contract §B, chanlun.ts:84.
DIVERGENCE_RATE = 0.9
# port-contract §B, chanlun.ts:395 — computeChanlun's minimum bar count.
MIN_BARS = 10


def ema(values: list[float], period: int) -> list[float | None]:
    """pandas ewm(span=period, adjust=False). port-contract §C.4, indicators.ts:17-28.

    alpha = 2/(period+1); one running float, seeded at the first finite
    value. Non-finite input emits None without disturbing the running state.
    """
    import math

    a = 2 / (period + 1)
    e: float | None = None
    out: list[float | None] = []
    for v in values:
        if v is None or not math.isfinite(v):
            out.append(None)
            continue
        e = v if e is None else a * v + (1 - a) * e
        out.append(e)
    return out


def macd_hist(closes: list[float]) -> list[float]:
    """MACD(12,26,9) histogram over closes. port-contract §C.4, chanlun.ts:179-185."""
    e12 = ema(closes, 12)
    e26 = ema(closes, 26)
    dif = [e12[i] - e26[i] for i in range(len(closes))]  # type: ignore[operator]
    dea = ema(dif, 9)
    return [dif[i] - dea[i] for i in range(len(dif))]  # type: ignore[operator]


def merge_inclusions(bars: list[ChanlunBar]) -> list[MergedK]:
    """包含处理 — greedy direction-dependent inclusion merge. port-contract §C.1, chanlun.ts:90-128.

    Tie-break asymmetry (must be reproduced exactly): up-merge high uses
    `>=` (tie moves the index), low uses strict `>` (tie does not); down-merge
    mirrors: low uses `<=`, high uses strict `<`.
    """
    m: list[MergedK] = []
    direction = 1  # 1 | -1; seeded "up" — washes out after the first non-inclusive pair
    for i, b in enumerate(bars):
        if not m:
            m.append(MergedK(high=b.high, low=b.low, hiIdx=i, loIdx=i))
            continue
        last = m[-1]
        inc = (last.high >= b.high and last.low <= b.low) or (
            b.high >= last.high and b.low <= last.low
        )
        if not inc:
            direction = 1 if b.high > last.high else -1
            m.append(MergedK(high=b.high, low=b.low, hiIdx=i, loIdx=i))
            continue
        if direction == 1:
            if b.high >= last.high:
                last.high = b.high
                last.hiIdx = i
            if b.low > last.low:
                last.low = b.low
                last.loIdx = i
        else:
            if b.low <= last.low:
                last.low = b.low
                last.loIdx = i
            if b.high < last.high:
                last.high = b.high
                last.hiIdx = i
    return m


def find_fractals(m: list[MergedK]) -> list[Fractal]:
    """分型 — strict fractals on merged candles. port-contract §C.2, chanlun.ts:133-149.

    All four comparisons per branch are strict; a tie on either high or low
    at either neighbor disqualifies the window as a fractal.
    """
    out: list[Fractal] = []
    for i in range(1, len(m) - 1):
        a, b, c = m[i - 1], m[i], m[i + 1]
        if b.high > a.high and b.high > c.high and b.low > a.low and b.low > c.low:
            out.append(Fractal(kind="top", mIdx=i, rawIdx=b.hiIdx, price=b.high))
        elif b.low < a.low and b.low < c.low and b.high < a.high and b.high < c.high:
            out.append(Fractal(kind="bottom", mIdx=i, rawIdx=b.loIdx, price=b.low))
    return out


def build_endpoints(fractals: list[Fractal]) -> list[Fractal]:
    """笔 endpoints — alternate fractals under the 新笔-style rule. port-contract §C.3, chanlun.ts:154-175.

    Same-kind: non-strict `>=`/`<=` replace (ties replace with the later
    fractal). Opposite-kind: BOTH the mIdx gap (`>= MIN_VERTEX_GAP`) AND a
    strict price improvement must hold to accept; a rejected opposite-kind
    fractal does NOT become the new `last`.
    """
    eps: list[Fractal] = []
    for f in fractals:
        if not eps:
            eps.append(f)
            continue
        last = eps[-1]
        if f.kind == last.kind:
            better = f.price >= last.price if f.kind == "top" else f.price <= last.price
            if better:
                eps[-1] = f
            continue
        valid_gap = f.mIdx - last.mIdx >= MIN_VERTEX_GAP
        valid_price = f.price > last.price if f.kind == "top" else f.price < last.price
        if valid_gap and valid_price:
            eps.append(f)
        # else: too close / wrong side — ignored (a later, better fractal wins)
    return eps


def build_legs(pts: list[VertexPt]) -> list[Leg]:
    """Pure adjacent-pair transform, no filtering. port-contract §C.6, chanlun.ts:214-228."""
    legs: list[Leg] = []
    for i in range(len(pts) - 1):
        legs.append(
            Leg(
                hi=max(pts[i].price, pts[i + 1].price),
                lo=min(pts[i].price, pts[i + 1].price),
                up=pts[i + 1].kind == "top",
                a=i,
                b=i + 1,
                rawA=pts[i].rawIdx,
                rawB=pts[i + 1].rawIdx,
            )
        )
    return legs


def build_pivots(legs: list[Leg]) -> list[Pivot]:
    """中枢 on 笔/段 — sliding-window scan with non-uniform advance. port-contract §C.7, chanlun.ts:233-259.

    `zg <= zd` rejects a degenerate/non-overlapping trio (single-leg slide
    on rejection). Once a pivot is found, the scan jumps straight to
    `exitLeg` (or the end) rather than resuming at `i+1` — the exit leg can
    seed the very next pivot's trio scan.
    """
    pivots: list[Pivot] = []
    i = 0
    while i <= len(legs) - 3:
        trio = legs[i : i + 3]
        zd = max(leg.lo for leg in trio)
        zg = min(leg.hi for leg in trio)
        if zg <= zd:
            i += 1
            continue
        last_leg = i + 2
        exit_leg: int | None = None
        exit_up = False
        for j in range(i + 3, len(legs)):
            if legs[j].lo > zg or legs[j].hi < zd:
                exit_leg = j
                exit_up = legs[j].lo > zg
                break
            last_leg = j
        pivots.append(
            Pivot(
                firstLeg=i,
                lastLeg=last_leg,
                exitLeg=exit_leg,
                exitUp=exit_up,
                zg=zg,
                zd=zd,
            )
        )
        i = exit_leg if exit_leg is not None else len(legs)
    return pivots


def pivots_to_zhongshus(
    pivots: list[Pivot], legs: list[Leg], pts: list[VertexPt]
) -> list[Zhongshu]:
    """Pure field projection from pivots to Zhongshu records. port-contract §C.7, chanlun.ts:261-273."""
    return [
        Zhongshu(
            start=pts[legs[p.firstLeg].a].time,
            end=pts[legs[p.lastLeg].b].time,
            zg=p.zg,
            zd=p.zd,
            confirmed=p.exitLeg is not None,
        )
        for p in pivots
    ]


def merge_overlapping_zhongshus(zs: list[Zhongshu]) -> list[Zhongshu]:
    """中枢升级 (pragmatic, flat, non-recursive). port-contract §C.8, chanlun.ts:279-294.

    Strict `<` overlap test — exact-touching zones do NOT merge. A merge
    widens `last` in place; `start` is left untouched (the envelope's start
    is always the first merged zone's original start). Non-merged zones are
    pushed as copies with `level` defaulted to 1 if not already set.
    """
    out: list[Zhongshu] = []
    for z in zs:
        last = out[-1] if out else None
        if last is not None and max(last.zd, z.zd) < min(last.zg, z.zg):
            last.zg = max(last.zg, z.zg)
            last.zd = min(last.zd, z.zd)
            last.end = z.end
            last.confirmed = last.confirmed and z.confirmed
            last.level = 2
        else:
            out.append(
                Zhongshu(
                    start=z.start,
                    end=z.end,
                    zg=z.zg,
                    zd=z.zd,
                    confirmed=z.confirmed,
                    level=z.level if z.level is not None else 1,
                )
            )
    return out


def resample_weekly(bars: list[ChanlunBar]) -> list[ChanlunBar]:
    """Group daily bars into calendar weeks (Monday key). port-contract §C.12, chanlun.ts:472-494.

    TRAP (port contract §G item 9): Python `date.weekday()` already equals
    the TS `(getUTCDay()+6)%7` — Monday=0 in both. Do NOT re-apply `(x+6)%7`
    on top of `date.weekday()`.

    Output `time` is the LAST session's date within that calendar week, not
    the Monday grouping key (which is never emitted).
    """
    import datetime as dt

    def monday(t: str) -> str:
        d = dt.date.fromisoformat(t)
        offset = d.weekday()  # Mon=0..Sun=6 "days since Monday" — already TS-equivalent
        return (d - dt.timedelta(days=offset)).isoformat()

    out: list[ChanlunBar] = []
    key = ""
    for b in bars:
        k = monday(b.time)
        if not out or k != key:
            key = k
            out.append(ChanlunBar(time=b.time, high=b.high, low=b.low, close=b.close))
            continue
        last = out[-1]
        last.high = max(last.high, b.high)
        last.low = min(last.low, b.low)
        last.close = b.close
        last.time = b.time
    return out
