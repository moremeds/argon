/**
 * Vendored + adapted from tradingview/lightweight-charts plugin-examples
 * (plugin-examples/src/plugins/bands-indicator + its helpers), Apache-2.0,
 * (c) TradingView, Inc. — https://github.com/tradingview/lightweight-charts
 *
 * Adaptations for argon:
 * - Upstream computed a demo ±10% envelope from the attached series' own
 *   data; this version renders EXPLICIT band values fed via setBandData()
 *   (an ATR or Bollinger envelope, depending on overlay mode).
 * - Times converted to epoch seconds for the autoscale binary search
 *   (upstream assumed numeric times; ours are 'yyyy-mm-dd' strings).
 * - Empty-data guards added (upstream crashed on points[0]).
 * - Gap-aware rendering: upstream always connected every point in the array.
 *   A `BandPoint` with upper/lower omitted now breaks the polyline into a new
 *   segment instead of drawing a straight line across a hole in the data
 *   (warm-up, or a bar with missing OHLC) — see `contiguousValidRuns`.
 */
import { CanvasRenderingTarget2D } from "fancy-canvas";
import type {
  AutoscaleInfo,
  Coordinate,
  IChartApi,
  IPrimitivePaneRenderer,
  IPrimitivePaneView,
  ISeriesApi,
  ISeriesPrimitive,
  Logical,
  SeriesAttachedParameter,
  SeriesOptionsMap,
  Time,
} from "lightweight-charts";

// A point with upper/lower omitted is a gap (mirrors lightweight-charts'
// LineData | WhitespaceData convention) — it breaks the polyline instead of
// connecting straight across a hole in the underlying data.
export type BandPoint =
  | { time: Time; upper: number; lower: number }
  | { time: Time; upper?: undefined; lower?: undefined };

export interface BandsIndicatorOptions {
  lineColor?: string;
  fillColor?: string;
  lineWidth?: number;
}

const defaults: Required<BandsIndicatorOptions> = {
  lineColor: "rgb(25, 200, 100)",
  fillColor: "rgba(25, 200, 100, 0.25)",
  lineWidth: 1,
};

function ensureDefined<T>(value: T | undefined): T {
  if (value === undefined) throw new Error("Value is undefined");
  return value;
}

// 'yyyy-mm-dd' | BusinessDay | UTCTimestamp -> epoch seconds (autoscale
// binary search only; rendering never converts).
function toEpochSec(t: Time | null | undefined, fallback: number): number {
  if (t == null) return fallback;
  if (typeof t === "number") return t;
  if (typeof t === "string") return Date.parse(t) / 1000;
  return Date.UTC(t.year, t.month - 1, t.day) / 1000;
}

type SearchDirection = "left" | "right";

class ClosestTimeIndexFinder<T extends { time: number }> {
  private numbers: T[];
  private cache: Map<string, number>;

  constructor(sortedNumbers: T[]) {
    this.numbers = sortedNumbers;
    this.cache = new Map();
  }

  public findClosestIndex(target: number, direction: SearchDirection): number {
    const cacheKey = `${target}:${direction}`;
    if (this.cache.has(cacheKey)) {
      return this.cache.get(cacheKey) as number;
    }
    const closestIndex = this._performSearch(target, direction);
    this.cache.set(cacheKey, closestIndex);
    return closestIndex;
  }

  private _performSearch(target: number, direction: SearchDirection): number {
    let low = 0;
    let high = this.numbers.length - 1;
    if (high < 0) return 0;
    if (target <= this.numbers[0].time) return 0;
    if (target >= this.numbers[high].time) return high;
    while (low <= high) {
      const mid = Math.floor((low + high) / 2);
      const num = this.numbers[mid].time;
      if (num === target) {
        return mid;
      } else if (num > target) {
        high = mid - 1;
      } else {
        low = mid + 1;
      }
    }
    return direction === "left" ? low : high;
  }
}

interface UpperLowerData {
  upper: number;
  lower: number;
}

// Gap points (upper/lower undefined) are skipped, not treated as 0 — a gap
// contributes nothing to the visible price range.
class UpperLowerInRange<T extends { upper?: number; lower?: number }> {
  private _arr: T[];
  private _chunkSize: number;
  private _cache: Map<string, UpperLowerData>;

  constructor(arr: T[], chunkSize = 10) {
    this._arr = arr;
    this._chunkSize = chunkSize;
    this._cache = new Map();
  }

  public getMinMax(startIndex: number, endIndex: number): UpperLowerData {
    const cacheKey = `${startIndex}:${endIndex}`;
    const hit = this._cache.get(cacheKey);
    if (hit) return hit;
    const result: UpperLowerData = { lower: Infinity, upper: -Infinity };
    const startChunkIndex = Math.floor(startIndex / this._chunkSize);
    const endChunkIndex = Math.floor(endIndex / this._chunkSize);
    for (
      let chunkIndex = startChunkIndex;
      chunkIndex <= endChunkIndex;
      chunkIndex++
    ) {
      const chunkStart = chunkIndex * this._chunkSize;
      const chunkEnd = Math.min(
        (chunkIndex + 1) * this._chunkSize - 1,
        this._arr.length - 1,
      );
      const chunkCacheKey = `${chunkStart}:${chunkEnd}`;
      const chunkHit = this._cache.get(chunkCacheKey);
      if (chunkHit) {
        this._check(chunkHit, result);
      } else {
        const chunkResult: UpperLowerData = {
          lower: Infinity,
          upper: -Infinity,
        };
        for (let i = chunkStart; i <= chunkEnd; i++) {
          const item = this._arr[i];
          if (item) this._check(item, chunkResult);
        }
        this._cache.set(chunkCacheKey, chunkResult);
        this._check(chunkResult, result);
      }
    }
    this._cache.set(cacheKey, result);
    return result;
  }

  private _check(
    item: { upper?: number; lower?: number },
    state: UpperLowerData,
  ) {
    if (item.lower == null || item.upper == null) return;
    if (item.lower < state.lower) state.lower = item.lower;
    if (item.upper > state.upper) state.upper = item.upper;
  }
}

abstract class PluginBase implements ISeriesPrimitive<Time> {
  private _chart: IChartApi | undefined = undefined;
  private _series: ISeriesApi<keyof SeriesOptionsMap> | undefined = undefined;
  private _requestUpdate?: () => void;

  protected requestUpdate(): void {
    if (this._requestUpdate) this._requestUpdate();
  }

  public attached({
    chart,
    series,
    requestUpdate,
  }: SeriesAttachedParameter<Time>) {
    this._chart = chart;
    this._series = series;
    this._requestUpdate = requestUpdate;
    this.requestUpdate();
  }

  public detached() {
    this._chart = undefined;
    this._series = undefined;
    this._requestUpdate = undefined;
  }

  public get chart(): IChartApi {
    return ensureDefined(this._chart);
  }

  public get series(): ISeriesApi<keyof SeriesOptionsMap> {
    return ensureDefined(this._series);
  }
}

interface BandRendererData {
  x: Coordinate | number;
  upper: Coordinate | number | null;
  lower: Coordinate | number | null;
}

interface BandViewData {
  data: BandRendererData[];
  options: Required<BandsIndicatorOptions>;
}

// Maximal [start, end] index ranges (inclusive) where upper is non-null.
// A run needs >= 2 points to draw a region; isolated single-point runs are
// dropped by callers, same as the original whole-array `length < 2` guard.
// Pulled out of drawBackground so the gap-segmentation logic is unit-testable
// without a canvas.
export function contiguousValidRuns(
  points: readonly { upper: unknown }[],
): Array<[number, number]> {
  const runs: Array<[number, number]> = [];
  let i = 0;
  while (i < points.length) {
    if (points[i].upper == null) {
      i++;
      continue;
    }
    let j = i;
    while (j + 1 < points.length && points[j + 1].upper != null) j++;
    if (j > i) runs.push([i, j]);
    i = j + 1;
  }
  return runs;
}

class BandsIndicatorPaneRenderer implements IPrimitivePaneRenderer {
  _viewData: BandViewData;
  constructor(data: BandViewData) {
    this._viewData = data;
  }
  draw() {}
  drawBackground(target: CanvasRenderingTarget2D) {
    const points: BandRendererData[] = this._viewData.data;
    // A gap point (null upper/lower) breaks the polyline into segments
    // instead of connecting straight across a hole in the underlying data.
    const runs = contiguousValidRuns(points);
    if (runs.length === 0) return; // adaptation: upstream crashed on empty data
    target.useBitmapCoordinateSpace((scope) => {
      const ctx = scope.context;
      ctx.scale(scope.horizontalPixelRatio, scope.verticalPixelRatio);

      ctx.strokeStyle = this._viewData.options.lineColor;
      ctx.lineWidth = this._viewData.options.lineWidth;
      ctx.beginPath();
      const region = new Path2D();
      const lines = new Path2D();
      for (const [i, j] of runs) {
        const upperAt = (k: number) => points[k].upper as number;
        const lowerAt = (k: number) => points[k].lower as number;
        region.moveTo(points[i].x, upperAt(i));
        lines.moveTo(points[i].x, upperAt(i));
        for (let k = i; k <= j; k++) {
          region.lineTo(points[k].x, upperAt(k));
          lines.lineTo(points[k].x, upperAt(k));
        }
        region.lineTo(points[j].x, lowerAt(j));
        lines.moveTo(points[j].x, lowerAt(j));
        for (let k = j - 1; k >= i; k--) {
          region.lineTo(points[k].x, lowerAt(k));
          lines.lineTo(points[k].x, lowerAt(k));
        }
        region.lineTo(points[i].x, upperAt(i));
        region.closePath();
      }
      ctx.stroke(lines);
      ctx.fillStyle = this._viewData.options.fillColor;
      ctx.fill(region);
    });
  }
}

class BandsIndicatorPaneView implements IPrimitivePaneView {
  _source: BandsIndicator;
  _data: BandViewData;

  constructor(source: BandsIndicator) {
    this._source = source;
    this._data = { data: [], options: this._source._options };
  }

  update() {
    const series = this._source.series;
    const timeScale = this._source.chart.timeScale();
    this._data.data = this._source._bandsData.map((d) => ({
      x: timeScale.timeToCoordinate(d.time) ?? -100,
      upper:
        d.upper != null ? (series.priceToCoordinate(d.upper) ?? -100) : null,
      lower:
        d.lower != null ? (series.priceToCoordinate(d.lower) ?? -100) : null,
    }));
  }

  renderer() {
    return new BandsIndicatorPaneRenderer(this._data);
  }
}

export class BandsIndicator
  extends PluginBase
  implements ISeriesPrimitive<Time>
{
  _paneViews: BandsIndicatorPaneView[];
  _bandsData: BandPoint[] = [];
  _options: Required<BandsIndicatorOptions>;
  _timeIndices: ClosestTimeIndexFinder<{ time: number }>;
  _upperLower: UpperLowerInRange<BandPoint>;

  constructor(options: BandsIndicatorOptions = {}) {
    super();
    this._options = { ...defaults, ...options };
    this._paneViews = [new BandsIndicatorPaneView(this)];
    this._timeIndices = new ClosestTimeIndexFinder([]);
    this._upperLower = new UpperLowerInRange([]);
  }

  /** Adaptation: explicit band values replace upstream's from-series demo. */
  setBandData(bands: BandPoint[]) {
    this._bandsData = bands;
    this._timeIndices = new ClosestTimeIndexFinder(
      bands.map((b) => ({ time: toEpochSec(b.time, 0) })),
    );
    this._upperLower = new UpperLowerInRange(bands, 4);
    this.requestUpdate();
  }

  updateAllViews() {
    this._paneViews.forEach((pw) => pw.update());
  }

  paneViews() {
    return this._paneViews;
  }

  autoscaleInfo(
    startTimePoint: Logical,
    endTimePoint: Logical,
  ): AutoscaleInfo | null {
    if (this._bandsData.length === 0) return null;
    const ts = this.chart.timeScale();
    const startTime = toEpochSec(
      ts.coordinateToTime(ts.logicalToCoordinate(startTimePoint) ?? 0),
      0,
    );
    const endTime = toEpochSec(
      ts.coordinateToTime(ts.logicalToCoordinate(endTimePoint) ?? 0),
      5_000_000_000,
    );
    const startIndex = this._timeIndices.findClosestIndex(startTime, "left");
    const endIndex = this._timeIndices.findClosestIndex(endTime, "right");
    const range = this._upperLower.getMinMax(startIndex, endIndex);
    if (!Number.isFinite(range.lower) || !Number.isFinite(range.upper))
      return null;
    return { priceRange: { minValue: range.lower, maxValue: range.upper } };
  }
}
