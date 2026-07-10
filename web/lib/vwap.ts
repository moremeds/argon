export type VwapBar = {
  as_of?: string | null;
  high?: number | null;
  low?: number | null;
  close?: number | null;
  volume?: number | null;
};

// Client-side mirror of cards/technicals.anchored_vwap — instant redraw on
// click; the server recompute remains the record of truth.
export function anchoredVwap(
  rows: readonly VwapBar[],
  anchorDate: string,
): { time: string; value: number }[] {
  let pv = 0;
  let vol = 0;
  const out: { time: string; value: number }[] = [];
  for (const r of rows) {
    const t = r.as_of;
    if (!t || t < anchorDate) continue;
    const { high, low, close, volume } = r;
    if (high != null && low != null && close != null && volume) {
      pv += ((high + low + close) / 3) * volume;
      vol += volume;
    }
    if (vol > 0) out.push({ time: t, value: pv / vol });
  }
  return out;
}
