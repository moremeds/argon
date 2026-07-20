/**
 * Fair value gaps — three-bar imbalances where the middle bar's move left a
 * price band untouched (bar i-1's high below bar i+1's low, or the mirror).
 *
 * Price action, not volume: this lives apart from lib/volumeProfile.ts on
 * purpose. Only gaps no later bar has traded back through are returned, since a
 * filled gap is just history.
 */

export type FvgBar = { time: string; high: number; low: number };

export type FairValueGap = {
  time: string; // the middle (gap-creating) bar
  top: number;
  bottom: number;
  bullish: boolean;
};

export function findFairValueGaps(
  bars: readonly FvgBar[],
  maxCount = 6,
): FairValueGap[] {
  if (bars.length < 3) return [];

  // Running extremes of everything strictly newer than the gap's third bar,
  // accumulated back-to-front so the fill test stays O(n).
  const out: FairValueGap[] = [];
  let minLowAfter = Infinity;
  let maxHighAfter = -Infinity;

  for (let i = bars.length - 2; i >= 1; i -= 1) {
    const prev = bars[i - 1];
    const next = bars[i + 1];
    const bullish = prev.high < next.low;
    const bearish = prev.low > next.high;
    if (bullish || bearish) {
      const top = bullish ? next.low : prev.low;
      const bottom = bullish ? prev.high : next.high;
      // Unfilled = nothing newer than the third bar entered the band AT ALL.
      // Deliberately stricter than the Pine original, which only closes a gap
      // once price traverses it completely — a partially-traded band is no
      // longer untraded, which is the whole claim the box makes.
      const open = bullish ? minLowAfter >= top : maxHighAfter <= bottom;
      if (open && out.length < maxCount) {
        out.push({ time: bars[i].time, top, bottom, bullish });
      }
    }
    // bars[i+1] is now "after" the next (older) gap we test.
    minLowAfter = Math.min(minLowAfter, next.low);
    maxHighAfter = Math.max(maxHighAfter, next.high);
  }
  return out.reverse(); // oldest first
}
