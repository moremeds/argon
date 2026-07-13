/**
 * Zhongshu (中枢) rectangles for the Chanlun overlay — a custom series
 * primitive in the mold of lib/lwc/bandsIndicator.ts (same attach/paneViews
 * lifecycle), but simpler: explicit rects fed via setRects(), no autoscale
 * contribution (pivot zones sit inside the candle range by construction).
 */
import { CanvasRenderingTarget2D } from "fancy-canvas";
import type {
  IChartApi,
  IPrimitivePaneRenderer,
  IPrimitivePaneView,
  ISeriesApi,
  ISeriesPrimitive,
  SeriesAttachedParameter,
  SeriesOptionsMap,
  Time,
} from "lightweight-charts";

export interface ZhongshuRect {
  start: Time; // 'yyyy-mm-dd', same representation as the attached series
  end: Time;
  zg: number; // upper edge
  zd: number; // lower edge
  confirmed: boolean; // false → dashed border (still extending)
}

export interface ChanlunZhongshuOptions {
  fillColor?: string;
  borderColor?: string;
}

const defaults: Required<ChanlunZhongshuOptions> = {
  fillColor: "rgba(120, 160, 255, 0.08)",
  borderColor: "rgba(120, 160, 255, 0.5)",
};

type RectPx = {
  x1: number;
  x2: number;
  y1: number;
  y2: number;
  confirmed: boolean;
};

class ZhongshuPaneRenderer implements IPrimitivePaneRenderer {
  constructor(
    private _rects: RectPx[],
    private _options: Required<ChanlunZhongshuOptions>,
  ) {}
  draw() {}
  drawBackground(target: CanvasRenderingTarget2D) {
    if (this._rects.length === 0) return;
    target.useBitmapCoordinateSpace((scope) => {
      const ctx = scope.context;
      ctx.scale(scope.horizontalPixelRatio, scope.verticalPixelRatio);
      for (const r of this._rects) {
        const w = r.x2 - r.x1;
        const h = r.y2 - r.y1;
        if (!(w > 0) || !Number.isFinite(h)) continue;
        ctx.fillStyle = this._options.fillColor;
        ctx.fillRect(r.x1, r.y1, w, h);
        ctx.strokeStyle = this._options.borderColor;
        ctx.lineWidth = 1;
        ctx.setLineDash(r.confirmed ? [] : [3, 3]);
        ctx.strokeRect(r.x1, r.y1, w, h);
      }
      ctx.setLineDash([]);
    });
  }
}

class ZhongshuPaneView implements IPrimitivePaneView {
  _rects: RectPx[] = [];
  constructor(private _source: ChanlunZhongshu) {}

  update() {
    const chart = this._source.chartApi();
    const series = this._source.seriesApi();
    this._rects = [];
    if (!chart || !series) return;
    const ts = chart.timeScale();
    const visible = ts.getVisibleRange();
    if (!visible) return;
    for (const d of this._source._data) {
      // timeToCoordinate → null outside the visible range: skip rects fully
      // off-screen, clamp the off-screen edge of partially visible ones.
      if (String(d.start) > String(visible.to)) continue;
      if (String(d.end) < String(visible.from)) continue;
      const x1 = ts.timeToCoordinate(d.start) ?? -10;
      const x2 = ts.timeToCoordinate(d.end) ?? ts.width() + 10;
      const y1 = series.priceToCoordinate(d.zg);
      const y2 = series.priceToCoordinate(d.zd);
      if (y1 == null || y2 == null) continue;
      this._rects.push({ x1, x2, y1, y2, confirmed: d.confirmed });
    }
  }

  renderer() {
    return new ZhongshuPaneRenderer(this._rects, this._source._options);
  }
}

export class ChanlunZhongshu implements ISeriesPrimitive<Time> {
  _data: ZhongshuRect[] = [];
  _options: Required<ChanlunZhongshuOptions>;
  private _paneViews: ZhongshuPaneView[];
  private _chart: IChartApi | undefined;
  private _series: ISeriesApi<keyof SeriesOptionsMap> | undefined;
  private _requestUpdate?: () => void;

  constructor(options: ChanlunZhongshuOptions = {}) {
    this._options = { ...defaults, ...options };
    this._paneViews = [new ZhongshuPaneView(this)];
  }

  attached({ chart, series, requestUpdate }: SeriesAttachedParameter<Time>) {
    this._chart = chart;
    this._series = series;
    this._requestUpdate = requestUpdate;
    this._requestUpdate?.();
  }

  detached() {
    this._chart = undefined;
    this._series = undefined;
    this._requestUpdate = undefined;
  }

  chartApi(): IChartApi | undefined {
    return this._chart;
  }

  seriesApi(): ISeriesApi<keyof SeriesOptionsMap> | undefined {
    return this._series;
  }

  setRects(rects: ZhongshuRect[]) {
    this._data = rects;
    this._requestUpdate?.();
  }

  updateAllViews() {
    this._paneViews.forEach((v) => v.update());
  }

  paneViews() {
    return this._paneViews;
  }
}
