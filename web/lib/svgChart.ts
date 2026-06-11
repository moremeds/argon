// Hand-rolled SVG chart helpers for the Volatility tab v2 panels.
// No external chart library — matches the GexProfileChart pattern.

export type Point = [number, number];

export function linearScale(
  domain: [number, number],
  range: [number, number],
): (v: number) => number {
  const [d0, d1] = domain;
  const [r0, r1] = range;
  const span = d1 - d0 || 1;
  return (v: number) => r0 + ((v - d0) / span) * (r1 - r0);
}

export function pathFromPoints(points: Point[]): string {
  if (points.length === 0) return "";
  return points.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x},${y}`).join(" ");
}

/**
 * Build an SVG path that BREAKS at null/undefined/non-finite values instead
 * of straight-line interpolating across them.
 *
 * Each `null` in the input ends the current sub-path; the next finite point
 * starts a fresh `M`. Use this for sparse series (e.g. `gex_flip`) where the
 * filtered-out version of `pathFromPoints` produces a misleading line that
 * connects across multi-bar gaps.
 *
 * **Isolated points:** when a finite point is surrounded by nulls on both
 * sides (or sits at start/end with a null neighbour), the sub-path would be
 * a lone `M{x},{y}` which SVG renders as nothing — sparse single-observation
 * series go invisible. To preserve those dots, an isolated point is emitted
 * as `M{x},{y} L{x},{y}` (a zero-length line). Consumers MUST set
 * `stroke-linecap="round"` (or "square") on the rendered `<path>` so the
 * zero-length segment becomes a visible dot of diameter = strokeWidth.
 */
export function pathFromNullablePoints(
  points: ReadonlyArray<Point | null>,
): string {
  function isFinitePoint(p: Point | null | undefined): p is Point {
    return p != null && Number.isFinite(p[0]) && Number.isFinite(p[1]);
  }
  let out = "";
  let pendingMove = true;
  for (let i = 0; i < points.length; i++) {
    const p = points[i];
    if (!isFinitePoint(p)) {
      pendingMove = true;
      continue;
    }
    const [x, y] = p;
    if (pendingMove) {
      out += `M${x},${y} `;
      // If the next index isn't a finite continuation, this point is
      // isolated — emit a zero-length line so a round-cap stroke draws a
      // dot rather than nothing.
      if (!isFinitePoint(points[i + 1])) {
        out += `L${x},${y} `;
      }
    } else {
      out += `L${x},${y} `;
    }
    pendingMove = false;
  }
  return out.trimEnd();
}

export function niceTicks(min: number, max: number, count = 5): number[] {
  if (!isFinite(min) || !isFinite(max) || min === max) return [min];
  // Heckbert nice-number rounding: snap the raw step to 1/2/5/10 × 10^k.
  // (The previous err-ladder compared in the wrong direction, so spans like
  // 7260–7600 fell through to a step of 10 → ~35 overlapping axis labels.)
  const raw = (max - min) / Math.max(1, count - 1);
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const frac = raw / mag;
  const nice = frac < 1.5 ? 1 : frac < 3 ? 2 : frac < 7 ? 5 : 10;
  const step = nice * mag;
  const start = Math.floor(min / step) * step;
  const end = Math.ceil(max / step) * step;
  const out: number[] = [];
  for (let i = 0; start + i * step <= end + step * 1e-6; i++) {
    out.push(start + i * step);
  }
  return out;
}

/**
 * Compute a chart's value domain safely from possibly-null/NaN values.
 *
 * Every Volatility-tab chart panel MUST go through this helper instead of
 * calling Math.min/Math.max directly on raw arrays. A single null poisons
 * the scale with NaN and produces blank SVG paths plus "NaN%" axis labels
 * (review finding I6). Returns null when fewer than 2 finite values exist;
 * callers render an empty-state in that case.
 */
export function finiteDomain(
  values: ReadonlyArray<number | null | undefined>,
): { lo: number; hi: number; count: number } | null {
  let lo = Infinity;
  let hi = -Infinity;
  let count = 0;
  for (const v of values) {
    if (v == null) continue;
    if (!Number.isFinite(v)) continue;
    if (v < lo) lo = v;
    if (v > hi) hi = v;
    count += 1;
  }
  if (count < 2) return null;
  return { lo, hi, count };
}
