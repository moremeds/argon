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

const binTotal = (b: VpBin) => b.buy + b.sell;
const binMid = (b: VpBin) => (b.low + b.high) / 2;

/** Bars only need a range to be tested for retests. */
export type RangeBar = { high: number; low: number };

/**
 * Distinct retests of a band: every time price re-enters it from outside.
 * A bar that stays inside across several sessions counts once.
 */
export function countRetests(
  bars: readonly RangeBar[],
  price: number,
  halfWidth: number,
): number {
  let count = 0;
  let wasInside = false;
  for (const b of bars) {
    const inside = b.high >= price - halfWidth && b.low <= price + halfWidth;
    if (inside && !wasInside) count += 1;
    wasInside = inside;
  }
  return count;
}

export type SrZone = {
  price: number; // band centre
  halfWidth: number;
  side: "support" | "resistance"; // relative to the reference price
  strength: number; // 0–100, share of the POC bin's volume
  touches: number;
};

export type SrZoneOptions = {
  maxPeaks?: number; // volume peaks to test before giving up
  maxPerSide?: number;
  minStrengthPct?: number; // floor as a % of POC volume
  minGapBins?: number; // minimum separation between kept zones
  widthMult?: number; // band thickness as a multiple of a bin
};

/**
 * High-volume nodes as support/resistance bands: repeatedly take the richest
 * remaining bin, blank its neighbourhood so the next pick is a distinct shelf,
 * and keep it if it clears the strength floor and the per-side cap.
 *
 * ponytail: greedy peak-picking, not a clustering algorithm. Volume profiles
 * are already smoothed by binning — the upgrade path is more bins, not k-means.
 */
export function findSrZones(
  profile: VolumeProfile,
  bars: readonly RangeBar[],
  refPrice: number,
  opts: SrZoneOptions = {},
): SrZone[] {
  const {
    maxPeaks = 16,
    maxPerSide = 5,
    minStrengthPct = 45,
    widthMult = 0.6,
  } = opts;

  const bins = profile.bins;
  if (bins.length === 0 || !(profile.maxBinVolume > 0)) return [];
  // Separation scales with resolution — a fixed bin count would blank a third
  // of a coarse profile per pick and only ever surface one shelf. ~9% of the
  // profile, matching the Pine original's 10-of-110 ratio.
  const minGapBins =
    opts.minGapBins ?? Math.max(2, Math.round(bins.length / 11));
  const binSize = bins[0].high - bins[0].low;
  const halfWidth = (binSize * widthMult) / 2;
  // Never let two bands overlap: the gap floor is the band thickness itself.
  const gapDist = Math.max(minGapBins * binSize, halfWidth * 2);
  const sepBins = Math.max(1, Math.round(gapDist / binSize));

  const remaining = bins.map(binTotal);
  const floor = (profile.maxBinVolume * minStrengthPct) / 100;
  const zones: SrZone[] = [];
  let supports = 0;
  let resistances = 0;

  for (let attempt = 0; attempt < maxPeaks; attempt += 1) {
    if (supports >= maxPerSide && resistances >= maxPerSide) break;
    let peak = 0;
    for (let i = 1; i < remaining.length; i += 1) {
      if (remaining[i] > remaining[peak]) peak = i;
    }
    const vol = remaining[peak];
    if (vol < floor) break;

    const price = binMid(bins[peak]);
    for (
      let i = Math.max(0, peak - sepBins);
      i <= Math.min(bins.length - 1, peak + sepBins);
      i += 1
    ) {
      remaining[i] = -1;
    }

    const tooClose = zones.some((z) => Math.abs(z.price - price) < gapDist);
    const side = price < refPrice ? "support" : "resistance";
    const sideFull =
      side === "support" ? supports >= maxPerSide : resistances >= maxPerSide;
    if (tooClose || sideFull) continue;

    zones.push({
      price,
      halfWidth,
      side,
      strength: Math.round((vol / profile.maxBinVolume) * 100),
      touches: countRetests(bars, price, halfWidth),
    });
    if (side === "support") supports += 1;
    else resistances += 1;
  }
  return zones;
}

/**
 * Low-volume nodes: thin shelves price tends to travel through rather than sit
 * in. Local minima under `maxPct` of the POC, walking outward from the
 * reference price so the nearest ones come first.
 */
export function findLvnLevels(
  profile: VolumeProfile,
  refPrice: number,
  opts: { maxPct?: number; floorPct?: number; maxCount?: number } = {},
): number[] {
  const { maxPct = 25, floorPct = 3, maxCount = 5 } = opts;
  const bins = profile.bins;
  if (bins.length < 3 || !(profile.maxBinVolume > 0)) return [];
  const ceiling = (profile.maxBinVolume * maxPct) / 100;
  const floor = (profile.maxBinVolume * floorPct) / 100;

  const isLvn = (i: number) => {
    if (i <= 0 || i >= bins.length - 1) return false;
    const v = binTotal(bins[i]);
    return (
      v < ceiling &&
      v > floor &&
      v <= binTotal(bins[i - 1]) &&
      v <= binTotal(bins[i + 1])
    );
  };

  // Bin holding refPrice; -1 means the price is above the whole profile.
  const hit = bins.findIndex((b) => b.high > refPrice);
  const start = hit === -1 ? bins.length - 1 : hit;
  const found: number[] = [];
  for (let d = 1; d < bins.length && found.length < maxCount; d += 1) {
    if (isLvn(start - d)) found.push(binMid(bins[start - d]));
    if (found.length < maxCount && isLvn(start + d)) {
      found.push(binMid(bins[start + d]));
    }
  }
  return found;
}
