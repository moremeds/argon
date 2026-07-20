/**
 * Visible-range volume profile (VRVP) — pure geometry, no canvas.
 *
 * Each bar's volume is spread evenly across the price bins its H/L range
 * touches, split buy (close >= open) vs sell. Yields the POC (highest-volume
 * bin) and the value area: bins expanded outward from the POC, always taking
 * the richer neighbour, until they hold `valuePct` of total volume.
 *
 * ponytail: even spread across the bar's range, not a per-tick distribution —
 * we only have daily OHLCV. Upgrade path is intraday bars, not a smarter model.
 */

export type VpBar = {
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
};

export type VpBin = {
  low: number; // bin price bounds
  high: number;
  buy: number;
  sell: number;
};

export type VolumeProfile = {
  bins: VpBin[]; // ascending price, contiguous, always `binCount` long
  pocIdx: number;
  valIdx: number; // value-area lower bin (inclusive)
  vahIdx: number; // value-area upper bin (inclusive)
  pocPrice: number; // mid price of the POC bin
  maxBinVolume: number; // buy+sell of the POC bin — the bar-length denominator
};

export function computeVolumeProfile(
  bars: readonly VpBar[],
  binCount = 60,
  valuePct = 70,
): VolumeProfile | null {
  if (bars.length < 2 || binCount < 2) return null;

  let hi = -Infinity;
  let lo = Infinity;
  for (const b of bars) {
    if (b.high > hi) hi = b.high;
    if (b.low < lo) lo = b.low;
  }
  const binSize = (hi - lo) / binCount;
  if (!(binSize > 0) || !Number.isFinite(binSize)) return null;

  const buy = new Array<number>(binCount).fill(0);
  const sell = new Array<number>(binCount).fill(0);
  const clampBin = (p: number) =>
    Math.max(0, Math.min(binCount - 1, Math.floor((p - lo) / binSize)));

  for (const b of bars) {
    if (!(b.volume > 0)) continue;
    const loBin = clampBin(b.low);
    const hiBin = clampBin(b.high);
    const share = b.volume / (hiBin - loBin + 1);
    const target = b.close >= b.open ? buy : sell;
    for (let i = loBin; i <= hiBin; i += 1) target[i] += share;
  }

  const total = buy.map((v, i) => v + sell[i]);
  let pocIdx = 0;
  for (let i = 1; i < binCount; i += 1) {
    if (total[i] > total[pocIdx]) pocIdx = i;
  }
  const grandTotal = total.reduce((a, b) => a + b, 0);
  if (!(grandTotal > 0)) return null;

  // Value area: walk outward from the POC, always absorbing the richer side.
  const target = (grandTotal * valuePct) / 100;
  let valIdx = pocIdx;
  let vahIdx = pocIdx;
  let acc = total[pocIdx];
  while (acc < target && (valIdx > 0 || vahIdx < binCount - 1)) {
    const up = vahIdx < binCount - 1 ? total[vahIdx + 1] : -1;
    const dn = valIdx > 0 ? total[valIdx - 1] : -1;
    if (up < 0 && dn < 0) break;
    if (up >= dn) {
      vahIdx += 1;
      acc += up;
    } else {
      valIdx -= 1;
      acc += dn;
    }
  }

  return {
    bins: Array.from({ length: binCount }, (_, i) => ({
      low: lo + i * binSize,
      high: lo + (i + 1) * binSize,
      buy: buy[i],
      sell: sell[i],
    })),
    pocIdx,
    valIdx,
    vahIdx,
    pocPrice: lo + (pocIdx + 0.5) * binSize,
    maxBinVolume: total[pocIdx],
  };
}
