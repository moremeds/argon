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

/**
 * Smooth path through `points` using a Fritsch–Carlson **monotone** cubic.
 *
 * Deliberately NOT Catmull-Rom. A Catmull-Rom spline overshoots: on the series
 * [0, 0, 2, 0, 0] it swings visibly below zero on both sides of the spike,
 * drawing a negative excursion that is not in the data. On a signed regime
 * chart that is a fabricated sign flip — the reader sees the series cross zero
 * when it never did. The monotone variant clamps tangents so the curve stays
 * within the range of its neighbouring samples, which costs nothing visually.
 *
 * Points must be sorted ascending by x. Fewer than 3 points falls back to a
 * straight polyline (a spline through 2 points is just the segment anyway).
 */
export function pathFromPointsSmooth(points: Point[]): string {
  const n = points.length;
  if (n < 3) return pathFromPoints(points);

  // Secant slopes between consecutive points.
  const dx: number[] = [];
  const delta: number[] = [];
  for (let i = 0; i < n - 1; i++) {
    const h = points[i + 1][0] - points[i][0];
    dx.push(h);
    delta.push(h === 0 ? 0 : (points[i + 1][1] - points[i][1]) / h);
  }

  // Initial tangents: one-sided at the ends, averaged in the interior.
  const m: number[] = new Array(n);
  m[0] = delta[0];
  m[n - 1] = delta[n - 2];
  for (let i = 1; i < n - 1; i++) m[i] = (delta[i - 1] + delta[i]) / 2;

  // Fritsch–Carlson limiter — this is the step that prevents overshoot.
  for (let i = 0; i < n - 1; i++) {
    if (delta[i] === 0) {
      m[i] = 0;
      m[i + 1] = 0;
      continue;
    }
    const a = m[i] / delta[i];
    const b = m[i + 1] / delta[i];
    const s = a * a + b * b;
    if (s > 9) {
      const t = 3 / Math.sqrt(s);
      m[i] = t * a * delta[i];
      m[i + 1] = t * b * delta[i];
    }
  }

  let d = `M${points[0][0]},${points[0][1]}`;
  for (let i = 0; i < n - 1; i++) {
    const h = dx[i] / 3;
    const [x0, y0] = points[i];
    const [x1, y1] = points[i + 1];
    d += ` C${x0 + h},${y0 + m[i] * h} ${x1 - h},${y1 - m[i + 1] * h} ${x1},${y1}`;
  }
  return d;
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

/**
 * Filled band between two edges sharing x positions: upper drawn forward, lower
 * reversed, closed into one polygon. No existing chart draws a two-edge band —
 * added for the SPX density cone's nested quantile bands.
 */
export function pathFromBand(upper: Point[], lower: Point[]): string {
  if (upper.length < 2 || lower.length < 2) return "";
  const fwd = upper.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x},${y}`).join(" ");
  const back = [...lower]
    .reverse()
    .map(([x, y]) => `L${x},${y}`)
    .join(" ");
  return `${fwd} ${back} Z`;
}
