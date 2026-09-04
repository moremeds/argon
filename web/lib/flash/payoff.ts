import type { Leg } from "@/components/flash/view";

/**
 * P&L at expiry, re-derived from the legs.
 *
 * WHY ARGON RE-DERIVES THIS instead of drawing the `pnlAt` points the view
 * already carries: those are five percentage offsets around spot — enough for
 * a smooth-looking curve, not enough to place the kinks. A payoff is piecewise
 * linear with corners exactly at the strikes, so evaluating AT the strikes
 * gives the true shape in five points where sampling needs a hundred and still
 * puts a corner a pixel off the strike it is labelled with.
 *
 * The re-derivation reads legs and net ONLY. Never a model-written price: the
 * chart's job is partly to show when the written max gain and the legs
 * disagree.
 */

export function intrinsic(
  right: "call" | "put",
  strike: number,
  spot: number,
): number {
  return right === "put"
    ? Math.max(strike - spot, 0)
    : Math.max(spot - strike, 0);
}

/**
 * Per contract (×100). `net` is POSITIVE for a debit paid — the sign
 * convention of the recorded runs, where a 710/665 put spread costs 7.74.
 */
export function pnlAt(legs: Leg[], net: number, spot: number): number {
  let value = 0;
  for (const leg of legs) {
    const sign = leg.action === "buy" ? 1 : -1;
    const ratio = leg.ratio ?? 1;
    value += sign * ratio * intrinsic(leg.right, leg.strike, spot);
  }
  return (value - net) * 100;
}

/** 18% of the span, both sides, over every strike plus spot plus breakeven. */
export function payoffDomain({
  strikes,
  spot,
  breakeven,
}: {
  strikes: number[];
  spot: number;
  breakeven: number;
}): [number, number] {
  const points = [...strikes, spot, breakeven];
  const lo = Math.min(...points);
  const hi = Math.max(...points);
  const pad = 0.18 * (hi - lo);
  return [lo - pad, hi + pad];
}

/**
 * The x values the curve is evaluated at: the domain floor, every strike
 * strictly inside it, the breakeven, the domain ceiling. Sorted, de-duplicated.
 * Nothing is sampled, so every kink is exact.
 */
export function payoffBreakpoints({
  strikes,
  breakeven,
  domain,
}: {
  strikes: number[];
  breakeven: number;
  domain: [number, number];
}): number[] {
  const [lo, hi] = domain;
  const inside = strikes.filter((k) => k > lo && k < hi);
  const all = [lo, ...inside, breakeven, hi];
  return Array.from(new Set(all)).sort((a, b) => a - b);
}
