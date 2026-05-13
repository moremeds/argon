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

export function niceTicks(min: number, max: number, count = 5): number[] {
  if (!isFinite(min) || !isFinite(max) || min === max) return [min];
  const span = max - min;
  const step = Math.pow(10, Math.floor(Math.log10(span / count)));
  const err = (count * step) / span;
  const adjusted =
    err >= 0.15
      ? step * 10
      : err >= 0.35
        ? step * 5
        : err >= 0.75
          ? step * 2
          : step;
  const start = Math.floor(min / adjusted) * adjusted;
  const end = Math.ceil(max / adjusted) * adjusted;
  const out: number[] = [];
  for (let v = start; v <= end + 1e-9; v += adjusted) out.push(v);
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
