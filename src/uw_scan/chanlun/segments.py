"""线段 (segments) — field-for-field port of web/lib/chanlunSeg.ts.

Algorithm source: docs/superpowers/specs/2026-07-14-chanlun-py-port-contract.md
(port contract) §C.16, chanlunSeg.ts:1-428. Batch, from-scratch port of
chan.py's seg_algo="chan" feature-sequence method (Vespa314/chan.py
Seg/SegListChan.py, Seg/EigenFX.py, Seg/Eigen.py, Combiner/KLine_Combiner.py).
chan.py is incremental; this rebuilds from scratch each call — the
do_init/used_to_be_sure machinery is deliberately not ported (port-contract
§D.7).

Highest-risk module in the port. Numeric semantics (port contract §E): no
epsilon/tolerance anywhere — every comparison operates on raw floats, no
fuzzing. Tie-break rules are asymmetric per function and must not be unified.
"""

from __future__ import annotations

from dataclasses import dataclass

from uw_scan.chanlun.types import BiVertex, Elem, SegStats, SegVertex, Stroke


def new_elem(s: Stroke, up: bool) -> Elem:
    """port-contract §C.16, chanlunSeg.ts:48-59."""
    return Elem(
        hi=s.hi,
        lo=s.lo,
        up=up,
        strokes=[s.idx],
        hiStroke=s.idx,
        loStroke=s.idx,
        lastHi=s.hi,
        lastLo=s.lo,
    )


def test_combine(
    el: Elem, s: Stroke, exclude_included: bool, allow_top_equal: int
) -> str:
    """chan.py CKLine_Combiner.test_combine on feature elements. port-contract §C.16, chanlunSeg.ts:62-76."""
    if el.hi >= s.hi and el.lo <= s.lo:
        return "combine"
    if el.hi <= s.hi and el.lo >= s.lo:
        if allow_top_equal == 1 and el.hi == s.hi and el.lo > s.lo:
            return "down"
        if allow_top_equal == -1 and el.lo == s.lo and el.hi < s.hi:
            return "up"
        return "included" if exclude_included else "combine"
    if el.hi > s.hi and el.lo > s.lo:
        return "down"
    return "up"


def try_add(el: Elem, s: Stroke, exclude_included: bool, allow_top_equal: int) -> str:
    """chan.py try_add: fold `s` into `el` along `el.up`'s FIXED direction on "combine".

    port-contract §C.16, chanlunSeg.ts:82-116. Envelope-edge updates use
    non-strict `>=`/`<=` on BOTH edges (unlike mergeInclusions' asymmetric
    strict/non-strict split, §C.1) — a tie on either edge still moves that
    edge's *Stroke index forward. A 一字 stroke (hi==lo) that wouldn't extend
    the envelope is absorbed without touching hi/lo/hiStroke/loStroke.
    """
    dir_ = test_combine(el, s, exclude_included, allow_top_equal)
    if dir_ != "combine":
        return dir_
    flat_no_extend = s.hi == s.lo and (s.hi <= el.hi if el.up else s.lo >= el.lo)
    if not flat_no_extend:
        if el.up:
            if s.hi >= el.hi:
                el.hi = s.hi
                el.hiStroke = s.idx
            if s.lo >= el.lo:
                el.lo = s.lo
                el.loStroke = s.idx
        else:
            if s.lo <= el.lo:
                el.lo = s.lo
                el.loStroke = s.idx
            if s.hi <= el.hi:
                el.hi = s.hi
                el.hiStroke = s.idx
        el.lastHi = s.hi
        el.lastLo = s.lo
    el.strokes.append(s.idx)
    return "combine"


class EigenFX:
    """chan.py CEigenFX: a detector for the END of one segment direction.

    up=True detects the end of an UP segment (fed DOWN strokes, seeks TOP).
    port-contract §C.16, chanlunSeg.ts:120-277.
    """

    def __init__(self, up: bool, strokes: list[Stroke]) -> None:
        self.up = up
        self.strokes = strokes
        self.ele: list[Elem | None] = [None, None, None]
        self.lst: list[int] = []
        self.gap = False
        self.fx: str | None = None
        self.actual_break_flag = True  # sticky within an instance (chan.py semantics)
        self.last_evidence: int | None = None

    @property
    def allow_top_equal(self) -> int:
        return 1 if self.up else -1

    def clear(self) -> None:
        self.ele = [None, None, None]
        self.lst = []
        self.gap = False
        self.fx = None

    def add(self, si: int) -> bool:
        """Feed one counter-direction stroke; True iff a valid fractal completes.

        port-contract §C.16, chanlunSeg.ts:145-170.
        """
        s = self.strokes[si]
        self.lst.append(si)
        if self.ele[0] is None:
            self.ele[0] = new_elem(s, self.up)  # merge dir = SEGMENT dir
            return False
        if self.ele[1] is None:
            # element 2: exclude_included=True — engulfing stroke starts a new elem
            if try_add(self.ele[0], s, True, 0) == "combine":
                return False
            self.ele[1] = new_elem(s, self.up)  # merge dir = SEGMENT dir again
            impossible = (
                self.ele[1].hi < self.ele[0].hi
                if self.up
                else self.ele[1].lo > self.ele[0].lo
            )  # 前两元素不可能成为分形
            return self.reset() if impossible else False
        # element 3: exclude_included=False — engulfing stroke MERGES into elem 2
        self.last_evidence = si
        dir_ = try_add(self.ele[1], s, False, self.allow_top_equal)
        if dir_ == "combine":
            return False
        self.ele[2] = new_elem(s, dir_ == "up")  # merge dir = LOCAL pairwise dir
        if not self.actual_break():
            return self.reset()
        self.update_fx()
        is_fx = self.fx == "top" if self.up else self.fx == "bottom"
        return True if is_fx else self.reset()

    def actual_break(self) -> bool:
        """chan.py EigenFX.actual_break. port-contract §C.16, chanlunSeg.ts:175-203.

        The counter-move must genuinely break past element 2's last
        stroke; at the data tail the fractal is accepted but flagged
        provisional. Port the three `if nn / if n / else` branches verbatim
        — this is NOT a "look 1-2 ahead" loop; each branch has its own
        distinct fallback semantics.
        """
        e1 = self.ele[1]
        e2 = self.ele[2]
        assert e1 is not None and e2 is not None
        if (self.up and e2.lo < e1.lastLo) or ((not self.up) and e2.hi > e1.lastHi):
            return True
        first = e2.strokes[0]
        s0 = self.strokes[first]
        n = self.strokes[first + 1] if first + 1 < len(self.strokes) else None
        nn = (
            self.strokes[first + 2] if first + 2 < len(self.strokes) else None
        )  # next same-direction stroke
        if nn is not None:
            breaks = nn.lo < s0.lo if self.up else nn.hi > s0.hi
            if breaks:
                self.last_evidence = first + 2
                return True
            if (not nn.sure) or (first + 3 >= len(self.strokes)):
                self.actual_break_flag = False
                return True
            return False
        if n is not None:
            extending = n.hi > e1.hi if self.up else n.lo < e1.lo
            if extending:
                return False
            self.actual_break_flag = False
            return True
        self.actual_break_flag = False
        return True

    def update_fx(self) -> None:
        """chan.py Eigen.update_fx with exclude_included=True + allow_top_equal.

        port-contract §C.16, chanlunSeg.ts:206-228.
        """
        pre, mid, next_ = self.ele[0], self.ele[1], self.ele[2]
        assert pre is not None and mid is not None and next_ is not None
        ate = self.allow_top_equal
        self.fx = None
        if (
            pre.hi < mid.hi
            and next_.hi <= mid.hi
            and next_.lo < mid.lo
            and (ate == 1 or next_.hi < mid.hi)
        ):
            self.fx = "top"
        elif (
            next_.hi > mid.hi
            and pre.lo > mid.lo
            and next_.lo >= mid.lo
            and (ate == -1 or next_.lo > mid.lo)
        ):
            self.fx = "bottom"
        self.gap = (self.fx == "top" and pre.hi < mid.lo) or (
            self.fx == "bottom" and pre.lo > mid.hi
        )

    def reset(self) -> bool:
        """chan.py reset (exclude_included branch). port-contract §C.16, chanlunSeg.ts:232-239.

        Drop the first fed stroke, replay the rest via `add`, early-exit
        True on the first replay call that returns True. Naturally
        recursive (each replayed `add` can itself call `reset` again).
        """
        rest = self.lst[1:]
        self.clear()
        for si in rest:
            if self.add(si):
                return True
        return False

    def get_peak_bi_idx(self) -> int:
        """port-contract §C.16, chanlunSeg.ts:243-246.

        The stroke index whose end vertex is the segment boundary: the
        stroke BEFORE the stroke carrying element 2's extreme.
        """
        mid = self.ele[1]
        assert mid is not None
        return (mid.hiStroke if self.up else mid.loStroke) - 1

    def can_be_end(self) -> bool | None:
        """True = confirmed end; None = provisional (tail). NEVER False (deviation #6).

        port-contract §C.16, chanlunSeg.ts:250-253.
        """
        if self.gap:
            return self.find_revert_fx(self.get_peak_bi_idx() + 2)
        return True if self.actual_break_flag else None

    def find_revert_fx(self, begin_idx: int) -> bool | None:
        """case-2 confirmation: the NEXT segment's counter strokes (same parity,
        step 2) must form their own valid fractal via a fresh reverse EigenFX.

        port-contract §C.16, chanlunSeg.ts:257-269.
        """
        if begin_idx < 0 or begin_idx >= len(self.strokes):
            return None
        rev = EigenFX(not self.up, self.strokes)
        i = begin_idx
        while i < len(self.strokes):
            if rev.add(i):
                t: bool | None = rev.can_be_end()
                if not rev.actual_break_flag:
                    t = None
                if t is True:
                    self.last_evidence = rev.lst[-1]
                return t
            i += 2
        return None

    def all_bi_sure(self) -> bool:
        """port-contract §C.16, chanlunSeg.ts:271-276."""
        if self.last_evidence is not None and not self.strokes[self.last_evidence].sure:
            return False
        return all(self.strokes[si].sure for si in self.lst)


@dataclass
class _Seg:
    """Internal segment-boundary record, not part of the public interface."""

    endV: int
    up: bool
    sure: bool


def build_segments(
    vertices: list[BiVertex], stats: SegStats | None = None
) -> list[SegVertex]:
    """线段 — chan.py feature-sequence method over stroke vertices.

    port-contract §C.16, chanlunSeg.ts:279-428. `vertices` is the FULL stroke
    vertex list including the provisional tail (§C.5).
    """
    if len(vertices) < 2:
        return []
    strokes: list[Stroke] = []
    for i in range(len(vertices) - 1):
        strokes.append(
            Stroke(
                idx=i,
                up=vertices[i + 1].kind == "top",
                hi=max(vertices[i].price, vertices[i + 1].price),
                lo=min(vertices[i].price, vertices[i + 1].price),
                sure=vertices[i].confirmed and vertices[i + 1].confirmed,
            )
        )

    segs: list[_Seg] = []
    begin = 0
    # Batch cal_seg_sure: fresh detectors per scan (resets the sticky
    # actual_break_flag, matching chan.py's per-scan EigenFX lifetime).
    while True:
        if begin >= len(strokes):
            break
        up_e = EigenFX(True, strokes)
        down_e = EigenFX(False, strokes)
        last_seg_dir: bool | None = segs[-1].up if segs else None
        fx: EigenFX | None = None
        for i in range(begin, len(strokes)):
            s = strokes[i]
            if (not s.up) and last_seg_dir is not True:
                if up_e.add(i):
                    fx = up_e
            elif s.up and last_seg_dir is not False:
                if down_e.add(i):
                    fx = down_e
            if len(segs) == 0:
                # First-segment bootstrap: direction goes to whichever detector
                # accumulates a 2nd element first; rollback if it loses it again.
                if up_e.ele[1] is not None and not s.up:
                    last_seg_dir = False  # imaginary predecessor DOWN -> first seg UP
                    down_e.clear()
                elif down_e.ele[1] is not None and s.up:
                    last_seg_dir = True
                    up_e.clear()
                if up_e.ele[1] is None and last_seg_dir is False and not s.up:
                    last_seg_dir = None
                elif down_e.ele[1] is None and last_seg_dir is True and s.up:
                    last_seg_dir = None
            if fx is not None:
                break
        if fx is None:
            break
        end_bi = fx.get_peak_bi_idx()
        t = fx.can_be_end()
        if stats is not None:
            if fx.gap:
                if t is True:
                    stats.case2Confirmed += 1
                else:
                    stats.case2Provisional += 1
            elif t is True:
                stats.case1 += 1
        start_v = segs[-1].endV if segs else 0
        end_v = end_bi + 1
        # SEG_END_VALUE_ERR analog: an up segment must rise start->end. Only the
        # first segment gets the skip-and-restart path (chan.py add_new_seg).
        value_ok = (
            vertices[end_v].price > vertices[start_v].price
            if fx.up
            else vertices[end_v].price < vertices[start_v].price
        )
        if not value_ok and len(segs) == 0:
            begin = end_bi + 1
            continue
        sure = t is True and value_ok and fx.all_bi_sure() and (end_v - start_v >= 3)
        segs.append(_Seg(endV=end_v, up=fx.up, sure=sure))
        begin = end_bi + 1
        if t is not True:
            break  # provisional tail segment — stop scanning

    # collect_left (peak method, batch/display form): leftover strokes become
    # alternating provisional segments to their running extremes.
    last_v = segs[-1].endV if segs else 0
    if len(segs) == 0 and len(vertices) > 1:
        # No segment at all: one provisional segment to the biggest excursion.
        hi_idx = -1
        lo_idx = -1
        for j in range(1, len(vertices)):
            v = vertices[j]
            if v.kind == "top" and (hi_idx == -1 or v.price >= vertices[hi_idx].price):
                hi_idx = j
            if v.kind == "bottom" and (
                lo_idx == -1 or v.price <= vertices[lo_idx].price
            ):
                lo_idx = j
        up_exc = vertices[hi_idx].price - vertices[0].price if hi_idx != -1 else -1
        dn_exc = vertices[0].price - vertices[lo_idx].price if lo_idx != -1 else -1
        pick = hi_idx if up_exc >= dn_exc else lo_idx
        if pick > 0:
            segs.append(_Seg(endV=pick, up=pick == hi_idx, sure=False))
            last_v = pick

    while last_v < len(vertices) - 1 and len(segs) > 0:
        want_top = not segs[-1].up  # alternate direction
        pick = -1
        for j in range(last_v + 1, len(vertices)):
            v = vertices[j]
            match = v.kind == "top" if want_top else v.kind == "bottom"
            if match and (
                pick == -1
                or (
                    v.price >= vertices[pick].price
                    if want_top
                    else v.price <= vertices[pick].price
                )
            ):
                pick = j
        if pick == -1:
            break  # uncovered tail: the 笔-level dashed tail shows it
        segs.append(_Seg(endV=pick, up=want_top, sure=False))
        last_v = pick

    if len(segs) == 0:
        return []
    out: list[SegVertex] = [
        SegVertex(
            time=vertices[0].time,
            price=vertices[0].price,
            kind=vertices[0].kind,
            confirmed=segs[0].sure,
        )
    ]
    for sg in segs:
        v = vertices[sg.endV]
        out.append(
            SegVertex(time=v.time, price=v.price, kind=v.kind, confirmed=sg.sure)
        )
    return out
