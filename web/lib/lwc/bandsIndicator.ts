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

export interface BandPoint {
  time: Time; // same representation as the attached series' data ('yyyy-mm-dd')
  upper: number;
  lower: number;
}

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

class UpperLowerInRange<T extends UpperLowerData> {
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

  private _check(item: UpperLowerData, state: UpperLowerData) {
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
  upper: Coordinate | number;
  lower: Coordinate | number;
}

interface BandViewData {
  data: BandRendererData[];
  options: Required<BandsIndicatorOptions>;
}

class BandsIndicatorPaneRenderer implements IPrimitivePaneRenderer {
  _viewData: BandViewData;
  constructor(data: BandViewData) {
    this._viewData = data;
  }
  draw() {}
  drawBackground(target: CanvasRenderingTarget2D) {
    const points: BandRendererData[] = this._viewData.data;
    if (points.length < 2) return; // adaptation: upstream crashed on empty data
    target.useBitmapCoordinateSpace((scope) => {
      const ctx = scope.context;
      ctx.scale(scope.horizontalPixelRatio, scope.verticalPixelRatio);

      ctx.strokeStyle = this._viewData.options.lineColor;
      ctx.lineWidth = this._viewData.options.lineWidth;
      ctx.beginPath();
      const region = new Path2D();
      const lines = new Path2D();
      region.moveTo(points[0].x, points[0].upper);
      lines.moveTo(points[0].x, points[0].upper);
      for (const point of points) {
        region.lineTo(point.x, point.upper);
        lines.lineTo(point.x, point.upper);
      }
      const end = points.length - 1;
      region.lineTo(points[end].x, points[end].lower);
      lines.moveTo(points[end].x, points[end].lower);
      for (let i = points.length - 2; i >= 0; i--) {
        region.lineTo(points[i].x, points[i].lower);
        lines.lineTo(points[i].x, points[i].lower);
      }
      region.lineTo(points[0].x, points[0].upper);
      region.closePath();
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
      upper: series.priceToCoordinate(d.upper) ?? -100,
      lower: series.priceToCoordinate(d.lower) ?? -100,
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
