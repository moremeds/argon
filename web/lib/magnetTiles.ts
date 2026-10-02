/**
 * Pure math behind the magnet view's four KPI tile charts.
 *
 * Lives in `lib/` rather than beside the components because every one of these
 * has a degenerate case that renders as *nothing* instead of throwing — a NaN
 * reaching an SVG `d` attribute makes the browser drop the path silently. These
 * are the functions worth a test.
 */

export type Num = number | null | undefined;

export const isNum = (v: Num): v is number => v != null && Number.isFinite(v);

/**
 * Simple moving average; null until the window fills.
 *
 * Non-finite inputs count as 0 rather than poisoning the running sum — one bad
 * bar would otherwise turn every subsequent value into NaN, because a running
 * sum never recovers from an NaN the way a recomputed window would.
 */
export function sma(values: Num[], n: number): (number | null)[] {
  if (n < 1) throw new RangeError(`sma window must be >= 1, got ${n}`);
  const out: (number | null)[] = [];
  const buf: number[] = [];
  let sum = 0;
  for (const v of values) {
    const x = isNum(v) ? v : 0;
    buf.push(x);
    sum += x;
    if (buf.length > n) sum -= buf.shift()!;
    out.push(buf.length === n ? sum / n : null);
  }
  return out;
}

/**
 * Compound daily change between two closes, in percent per session.
 *
 * Returns null rather than NaN on every degenerate input — out-of-range
 * indices, a non-positive price (`Math.pow` of a negative base to a fractional
 * exponent is NaN), or a zero-length span.
 */
export function velocity(
  closes: number[],
  from: number,
  to: number,
): number | null {
  if (from < 0 || to >= closes.length || to <= from) return null;
  const a = closes[from];
  const b = closes[to];
  if (!isNum(a) || !isNum(b) || a <= 0 || b <= 0) return null;
  return (Math.pow(b / a, 1 / (to - from)) - 1) * 100;
}

/**
 * Padded plot domain over the finite values. Null when fewer than two points
 * are finite — one point is not a line, and drawing it would imply a trend.
 *
 * `includeZero` is what keeps a signed series' zero line inside the frame; a
 * momentum chart whose zero sits off-canvas has no readable sign.
 */
export function tileDomain(
  values: Num[],
  opts?: { includeZero?: boolean },
): { lo: number; hi: number } | null {
  const ok = values.filter(isNum);
  if (ok.length < 2) return null;
  let lo = Math.min(...ok);
  let hi = Math.max(...ok);
  if (opts?.includeZero) {
    lo = Math.min(lo, 0);
    hi = Math.max(hi, 0);
  }
  // A flat series has lo === hi. Fall back through: 10% of the span, then 10%
  // of the level, then 1 — so a flat series at 0 still gets a finite domain
  // instead of a zero-width one that scales every point to the same pixel.
  const pad = (hi - lo) * 0.1 || Math.abs(hi) * 0.1 || 1;
  return { lo: lo - pad, hi: hi + pad };
}

/** Volume bars get a shorter window — 90 bars at tile width are 1px slivers. */
const VOL_TILE_BARS = 34;

export type VolumeTile = {
  /** Last VOL_TILE_BARS candles as {volume, up} bars — the tile's chart input. */
  bars: { volume: Num; up: boolean }[];
  /** SMA20 of volume aligned to `bars` (leading nulls until it fills). */
  ma: (number | null)[];
  lastVol: number | null;
  lastVolMa: number | null;
  /** lastVol / lastVolMa — null when either is missing or the MA is 0. */
  ratio: number | null;
};

// The volume tile's inputs, from the magnets candles (NOT technicals.series —
// the two sources sit on different as_of dates, and the bars must line up with
// the chart directly above them). SMA20 runs over ALL candles then slices to
// the tile window, so the MA is converged at the window's left edge.
export function volumeTile(
  candles: readonly { volume: Num; open: number; close: number }[],
): VolumeTile {
  const bars = candles.slice(-VOL_TILE_BARS).map((c) => ({
    volume: c.volume,
    up: c.close >= c.open,
  }));
  const ma = sma(
    candles.map((c) => c.volume),
    20,
  ).slice(-VOL_TILE_BARS);
  const lastVol = candles.at(-1)?.volume ?? null;
  const lastVolMa = ma.at(-1) ?? null;
  const ratio = lastVol != null && lastVolMa ? lastVol / lastVolMa : null;
  return { bars, ma, lastVol, lastVolMa, ratio };
}

export type KinematicsLeg = {
  /** Compound %/session over the last leg. */
  v: number | null;
  /** Change in velocity per session across the last two legs. */
  accel: number | null;
};

// Kinematics, spec §1.1 layer 6: 1st and 2nd derivative of price — the last
// KIN sessions' velocity vs the leg before it. Descriptive only — no threshold
// is applied and no ACCEL/DECEL verdict is printed, because picking those
// cut-offs would be inventing a signal the reference never validated either.
export function kinematicsLeg(closes: number[], leg = 5): KinematicsLeg {
  const n = closes.length;
  const v = velocity(closes, n - 1 - leg, n - 1);
  const vPrev = velocity(closes, n - 1 - 2 * leg, n - 1 - leg);
  return { v, accel: v != null && vPrev != null ? (v - vPrev) / leg : null };
}
