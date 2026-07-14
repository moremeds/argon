// 线段 (segments) — chan.py seg_algo="chan" feature-sequence method, ported
// for BATCH recompute (chan.py is incremental; we rebuild from scratch each
// render, so do_init/used_to_be_sure machinery is unnecessary). Both
// termination cases: case 1 (no 缺口) ends immediately; case 2 (缺口) needs
// the counter-move to form its own fractal (recursive findRevertFx).
// Mechanics extracted 2026-07-14 from Vespa314/chan.py Seg/SegListChan.py,
// Seg/EigenFX.py, Seg/Eigen.py, Combiner/KLine_Combiner.py — see the v2
// addendum in docs/research/2026-07-14-chanlun-tv-view-research.md.
import type { BiVertex } from "@/lib/chanlun";

export type SegVertex = {
  time: string;
  price: number;
  kind: "top" | "bottom";
  confirmed: boolean; // false on the provisional tail — same contract as BiVertex
};

export type SegStats = {
  case1: number;
  case2Confirmed: number;
  case2Provisional: number;
};

type Stroke = {
  idx: number;
  up: boolean;
  hi: number;
  lo: number;
  sure: boolean; // both endpoint vertices confirmed (batch analog of is_used_to_be_sure)
};

type CombineDir = "combine" | "included" | "up" | "down";

// Feature-sequence element: an inclusion-merged run of counter-direction
// strokes (chan.py CEigen). Merge direction is FIXED per element, not
// recomputed per stroke.
type Elem = {
  hi: number;
  lo: number;
  up: boolean; // merge direction
  strokes: number[];
  hiStroke: number; // stroke carrying the element high (GetPeakBiIdx)
  loStroke: number;
  lastHi: number; // last merged stroke's own range (actual_break)
  lastLo: number;
};

function newElem(s: Stroke, up: boolean): Elem {
  return {
    hi: s.hi,
    lo: s.lo,
    up,
    strokes: [s.idx],
    hiStroke: s.idx,
    loStroke: s.idx,
    lastHi: s.hi,
    lastLo: s.lo,
  };
}

// chan.py CKLine_Combiner.test_combine on feature elements.
function testCombine(
  el: Elem,
  s: Stroke,
  excludeIncluded: boolean,
  allowTopEqual: 0 | 1 | -1,
): CombineDir {
  if (el.hi >= s.hi && el.lo <= s.lo) return "combine";
  if (el.hi <= s.hi && el.lo >= s.lo) {
    if (allowTopEqual === 1 && el.hi === s.hi && el.lo > s.lo) return "down";
    if (allowTopEqual === -1 && el.lo === s.lo && el.hi < s.hi) return "up";
    return excludeIncluded ? "included" : "combine";
  }
  if (el.hi > s.hi && el.lo > s.lo) return "down";
  return "up";
}

// chan.py try_add: on "combine", fold the stroke into the element along the
// element's FIXED direction (up: envelope rides up — hi=max, lo=max; down:
// mirror). 一字 stroke (hi==lo) that wouldn't extend the envelope is absorbed
// without touching it.
function tryAdd(
  el: Elem,
  s: Stroke,
  excludeIncluded: boolean,
  allowTopEqual: 0 | 1 | -1,
): CombineDir {
  const dir = testCombine(el, s, excludeIncluded, allowTopEqual);
  if (dir !== "combine") return dir;
  const flatNoExtend = s.hi === s.lo && (el.up ? s.hi <= el.hi : s.lo >= el.lo);
  if (!flatNoExtend) {
    if (el.up) {
      if (s.hi >= el.hi) {
        el.hi = s.hi;
        el.hiStroke = s.idx;
      }
      if (s.lo >= el.lo) {
        el.lo = s.lo;
        el.loStroke = s.idx;
      }
    } else {
      if (s.lo <= el.lo) {
        el.lo = s.lo;
        el.loStroke = s.idx;
      }
      if (s.hi <= el.hi) {
        el.hi = s.hi;
        el.hiStroke = s.idx;
      }
    }
    el.lastHi = s.hi;
    el.lastLo = s.lo;
  }
  el.strokes.push(s.idx);
  return "combine";
}

// chan.py CEigenFX: a detector for the END of one segment direction.
// up=true detects the end of an UP segment (fed DOWN strokes, seeks TOP).
class EigenFX {
  ele: [Elem | null, Elem | null, Elem | null] = [null, null, null];
  lst: number[] = [];
  gap = false;
  fx: "top" | "bottom" | null = null;
  actualBreakFlag = true; // sticky within an instance (chan.py semantics)
  lastEvidence: number | null = null;

  constructor(
    readonly up: boolean,
    private readonly strokes: readonly Stroke[],
  ) {}

  private get allowTopEqual(): 1 | -1 {
    return this.up ? 1 : -1;
  }

  clear(): void {
    this.ele = [null, null, null];
    this.lst = [];
    this.gap = false;
    this.fx = null;
  }

  // Feed one counter-direction stroke; true when a valid fractal completes.
  add(si: number): boolean {
    const s = this.strokes[si];
    this.lst.push(si);
    if (!this.ele[0]) {
      this.ele[0] = newElem(s, this.up); // merge dir = SEGMENT dir
      return false;
    }
    if (!this.ele[1]) {
      // element 2: exclude_included=true — engulfing stroke starts a new elem
      if (tryAdd(this.ele[0], s, true, 0) === "combine") return false;
      this.ele[1] = newElem(s, this.up); // merge dir = SEGMENT dir again
      const impossible = this.up
        ? this.ele[1].hi < this.ele[0].hi
        : this.ele[1].lo > this.ele[0].lo; // 前两元素不可能成为分形
      return impossible ? this.reset() : false;
    }
    // element 3: exclude_included=false — engulfing stroke MERGES into elem 2
    this.lastEvidence = si;
    const dir = tryAdd(this.ele[1], s, false, this.allowTopEqual);
    if (dir === "combine") return false;
    this.ele[2] = newElem(s, dir === "up"); // merge dir = LOCAL pairwise dir
    if (!this.actualBreak()) return this.reset();
    this.updateFx();
    const isFx = this.up ? this.fx === "top" : this.fx === "bottom";
    return isFx ? true : this.reset();
  }

  // chan.py EigenFX.actual_break — the counter-move must genuinely break past
  // element 2's last stroke; at the data tail the fractal is accepted but
  // flagged provisional.
  private actualBreak(): boolean {
    const e1 = this.ele[1] as Elem;
    const e2 = this.ele[2] as Elem;
    if (this.up ? e2.lo < e1.lastLo : e2.hi > e1.lastHi) return true;
    const first = e2.strokes[0];
    const s0 = this.strokes[first];
    const nn = this.strokes[first + 2]; // next same-direction stroke
    const n = this.strokes[first + 1];
    if (nn) {
      const breaks = this.up ? nn.lo < s0.lo : nn.hi > s0.hi;
      if (breaks) {
        this.lastEvidence = first + 2;
        return true;
      }
      if (!nn.sure || first + 3 >= this.strokes.length) {
        this.actualBreakFlag = false;
        return true;
      }
      return false;
    }
    if (n) {
      const extending = this.up ? n.hi > e1.hi : n.lo < e1.lo;
      if (extending) return false;
      this.actualBreakFlag = false;
      return true;
    }
    this.actualBreakFlag = false;
    return true;
  }

  // chan.py Eigen.update_fx with exclude_included=true + allow_top_equal.
  private updateFx(): void {
    const [pre, mid, next] = this.ele as [Elem, Elem, Elem];
    const ate = this.allowTopEqual;
    this.fx = null;
    if (
      pre.hi < mid.hi &&
      next.hi <= mid.hi &&
      next.lo < mid.lo &&
      (ate === 1 || next.hi < mid.hi)
    ) {
      this.fx = "top";
    } else if (
      next.hi > mid.hi &&
      pre.lo > mid.lo &&
      next.lo >= mid.lo &&
      (ate === -1 || next.lo > mid.lo)
    ) {
      this.fx = "bottom";
    }
    this.gap =
      (this.fx === "top" && pre.hi < mid.lo) ||
      (this.fx === "bottom" && pre.lo > mid.hi);
  }

  // chan.py reset (exclude_included branch): drop the first stroke, replay
  // the rest; true iff a fractal completes during the replay.
  reset(): boolean {
    const rest = this.lst.slice(1);
    this.clear();
    for (let i = 0; i < rest.length; i++) {
      if (this.add(rest[i])) return true;
    }
    return false;
  }

  // The stroke index whose end vertex is the segment boundary: the stroke
  // BEFORE the feature stroke carrying element 2's extreme.
  getPeakBiIdx(): number {
    const mid = this.ele[1] as Elem;
    return (this.up ? mid.hiStroke : mid.loStroke) - 1;
  }

  // true = confirmed end; null = provisional (tail). Never false — chan.py
  // removed the threshold-break rejection (issue #272).
  canBeEnd(): true | null {
    if (this.gap) return this.findRevertFx(this.getPeakBiIdx() + 2);
    return this.actualBreakFlag ? true : null;
  }

  // case-2 confirmation: the NEXT segment's counter strokes (same parity,
  // step 2) must form their own valid fractal via the same machinery.
  private findRevertFx(beginIdx: number): true | null {
    if (beginIdx < 0 || beginIdx >= this.strokes.length) return null;
    const rev = new EigenFX(!this.up, this.strokes);
    for (let i = beginIdx; i < this.strokes.length; i += 2) {
      if (rev.add(i)) {
        let t: true | null = rev.canBeEnd();
        if (!rev.actualBreakFlag) t = null;
        if (t === true) this.lastEvidence = rev.lst[rev.lst.length - 1];
        return t;
      }
    }
    return null;
  }

  allBiSure(): boolean {
    if (this.lastEvidence != null && !this.strokes[this.lastEvidence].sure) {
      return false;
    }
    return this.lst.every((si) => this.strokes[si].sure);
  }
}

export function buildSegments(
  vertices: readonly BiVertex[],
  stats?: SegStats,
): SegVertex[] {
  if (vertices.length < 2) return [];
  const strokes: Stroke[] = [];
  for (let i = 0; i + 1 < vertices.length; i++) {
    strokes.push({
      idx: i,
      up: vertices[i + 1].kind === "top",
      hi: Math.max(vertices[i].price, vertices[i + 1].price),
      lo: Math.min(vertices[i].price, vertices[i + 1].price),
      sure: vertices[i].confirmed && vertices[i + 1].confirmed,
    });
  }

  type Seg = { endV: number; up: boolean; sure: boolean };
  const segs: Seg[] = [];
  let begin = 0;
  // Batch cal_seg_sure: fresh detectors per scan (resets the sticky
  // actualBreakFlag, matching chan.py's per-scan EigenFX lifetime).
  for (;;) {
    if (begin >= strokes.length) break;
    const upE = new EigenFX(true, strokes);
    const downE = new EigenFX(false, strokes);
    let lastSegDir: boolean | null = segs.length
      ? segs[segs.length - 1].up
      : null;
    let fx: EigenFX | null = null;
    for (let i = begin; i < strokes.length; i++) {
      const s = strokes[i];
      if (!s.up && lastSegDir !== true) {
        if (upE.add(i)) fx = upE;
      } else if (s.up && lastSegDir !== false) {
        if (downE.add(i)) fx = downE;
      }
      if (segs.length === 0) {
        // First-segment bootstrap: direction goes to whichever detector
        // accumulates a 2nd element first; rollback if it loses it again.
        if (upE.ele[1] && !s.up) {
          lastSegDir = false; // imaginary predecessor DOWN → first seg UP
          downE.clear();
        } else if (downE.ele[1] && s.up) {
          lastSegDir = true;
          upE.clear();
        }
        if (!upE.ele[1] && lastSegDir === false && !s.up) lastSegDir = null;
        else if (!downE.ele[1] && lastSegDir === true && s.up) {
          lastSegDir = null;
        }
      }
      if (fx) break;
    }
    if (!fx) break;
    const endBi = fx.getPeakBiIdx();
    const t = fx.canBeEnd();
    if (stats) {
      if (fx.gap) {
        if (t === true) stats.case2Confirmed++;
        else stats.case2Provisional++;
      } else if (t === true) stats.case1++;
    }
    const startV = segs.length ? segs[segs.length - 1].endV : 0;
    const endV = endBi + 1;
    // SEG_END_VALUE_ERR analog: an up segment must rise start→end. Only the
    // first segment gets the skip-and-restart path (chan.py add_new_seg).
    const valueOk = fx.up
      ? vertices[endV].price > vertices[startV].price
      : vertices[endV].price < vertices[startV].price;
    if (!valueOk && segs.length === 0) {
      begin = endBi + 1;
      continue;
    }
    const sure = t === true && valueOk && fx.allBiSure() && endV - startV >= 3;
    segs.push({ endV, up: fx.up, sure });
    begin = endBi + 1;
    if (t !== true) break; // provisional tail segment — stop scanning
  }

  // collect_left (peak method, batch/display form): leftover strokes become
  // alternating provisional segments to their running extremes.
  let lastV = segs.length ? segs[segs.length - 1].endV : 0;
  if (segs.length === 0 && vertices.length > 1) {
    // No segment at all: one provisional segment to the biggest excursion.
    let hiIdx = -1;
    let loIdx = -1;
    for (let j = 1; j < vertices.length; j++) {
      const v = vertices[j];
      if (
        v.kind === "top" &&
        (hiIdx === -1 || v.price >= vertices[hiIdx].price)
      ) {
        hiIdx = j;
      }
      if (
        v.kind === "bottom" &&
        (loIdx === -1 || v.price <= vertices[loIdx].price)
      ) {
        loIdx = j;
      }
    }
    const upExc = hiIdx === -1 ? -1 : vertices[hiIdx].price - vertices[0].price;
    const dnExc = loIdx === -1 ? -1 : vertices[0].price - vertices[loIdx].price;
    const pick = upExc >= dnExc ? hiIdx : loIdx;
    if (pick > 0) {
      segs.push({ endV: pick, up: pick === hiIdx, sure: false });
      lastV = pick;
    }
  }
  while (lastV < vertices.length - 1 && segs.length > 0) {
    const wantTop = !segs[segs.length - 1].up; // alternate direction
    let pick = -1;
    for (let j = lastV + 1; j < vertices.length; j++) {
      const v = vertices[j];
      const match = wantTop ? v.kind === "top" : v.kind === "bottom";
      if (
        match &&
        (pick === -1 ||
          (wantTop
            ? v.price >= vertices[pick].price
            : v.price <= vertices[pick].price))
      ) {
        pick = j;
      }
    }
    if (pick === -1) break; // uncovered tail: the 笔-level dashed tail shows it
    segs.push({ endV: pick, up: wantTop, sure: false });
    lastV = pick;
  }

  if (segs.length === 0) return [];
  const out: SegVertex[] = [
    {
      time: vertices[0].time,
      price: vertices[0].price,
      kind: vertices[0].kind,
      confirmed: segs[0].sure,
    },
  ];
  for (const sg of segs) {
    const v = vertices[sg.endV];
    out.push({
      time: v.time,
      price: v.price,
      kind: v.kind,
      confirmed: sg.sure,
    });
  }
  return out;
}
