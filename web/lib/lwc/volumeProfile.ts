/**
 * Visible-range volume profile (VRVP) drawn against the right edge of the price
 * pane — horizontal bars growing leftward, buy volume hugging the axis, sell
 * volume stacked outside it. Same attach/paneViews lifecycle as
 * lib/lwc/chanlunZhongshu.ts; the binning math lives in lib/volumeProfile.ts.
 *
 * The profile is recomputed from the visible time range on every view update
 * (that's what makes it "visible range"), memoized on the range so crosshair
 * moves don't re-bin.
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
import {
  computeVolumeProfile,
  type VolumeProfile,
  type VpBar,
} from "@/lib/volumeProfile";

export type VolumeProfileBar = VpBar & { time: Time };

export interface VolumeProfileOptions {
  buyColor?: string;
  sellColor?: string;
  pocColor?: string;
  bins?: number;
  valuePct?: number;
  /** Profile width as a fraction of pane width, clamped by min/max px. */
  widthFrac?: number;
  minWidthPx?: number;
  maxWidthPx?: number;
}

const defaults: Required<VolumeProfileOptions> = {
  buyColor: "rgba(0, 137, 123, 0.85)",
  sellColor: "rgba(156, 39, 176, 0.85)",
  pocColor: "rgba(255, 167, 38, 0.9)",
  bins: 60,
  valuePct: 70,
  widthFrac: 0.22,
  minWidthPx: 70,
  maxWidthPx: 240,
};

type RowPx = {
  yTop: number;
  yBottom: number;
  buyFrac: number; // 0..1 of the profile width
  sellFrac: number;
  inValueArea: boolean;
};

type ViewPx = { rows: RowPx[]; pocY: number | null; pocPrice: number };

class VolumeProfileRenderer implements IPrimitivePaneRenderer {
  constructor(
    private _view: ViewPx | null,
    private _options: Required<VolumeProfileOptions>,
  ) {}

  draw() {}

  // Background: the profile sits behind the candles it summarizes. Our right
  // gap is only RIGHT_GAP_BARS wide, so a foreground profile would bury the
  // newest bars — the layer, not alpha, keeps price legible.
  drawBackground(target: CanvasRenderingTarget2D) {
    const view = this._view;
    if (!view || view.rows.length === 0) return;
    target.useBitmapCoordinateSpace((scope) => {
      const ctx = scope.context;
      ctx.save();
      ctx.scale(scope.horizontalPixelRatio, scope.verticalPixelRatio);
      const right = scope.mediaSize.width;
      const width = Math.max(
        this._options.minWidthPx,
        Math.min(this._options.maxWidthPx, right * this._options.widthFrac),
      );

      for (const r of view.rows) {
        const h = Math.max(1, r.yBottom - r.yTop - 0.5); // hairline gap between rows
        const buyLen = r.buyFrac * width;
        const sellLen = r.sellFrac * width;
        if (buyLen + sellLen < 0.5) continue;
        // Outside the value area the bins are context, not levels — dim them.
        ctx.globalAlpha = r.inValueArea ? 1 : 0.4;
        if (buyLen > 0) {
          ctx.fillStyle = this._options.buyColor;
          ctx.fillRect(right - buyLen, r.yTop, buyLen, h);
        }
        if (sellLen > 0) {
          ctx.fillStyle = this._options.sellColor;
          ctx.fillRect(right - buyLen - sellLen, r.yTop, sellLen, h);
        }
      }

      ctx.globalAlpha = 1;
      if (view.pocY != null) {
        ctx.strokeStyle = this._options.pocColor;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(right - width, view.pocY);
        ctx.lineTo(right, view.pocY);
        ctx.stroke();
        ctx.fillStyle = this._options.pocColor;
        ctx.font = "10px monospace";
        ctx.textBaseline = "bottom";
        ctx.fillText(
          `POC ${view.pocPrice.toFixed(2)}`,
          right - width,
          view.pocY - 2,
        );
      }
      ctx.restore();
    });
  }
}

class VolumeProfilePaneView implements IPrimitivePaneView {
  private _view: ViewPx | null = null;
  private _cacheKey = "";
  private _profile: VolumeProfile | null = null;

  constructor(private _source: VolumeProfileIndicator) {}

  update() {
    const chart = this._source.chartApi();
    const series = this._source.seriesApi();
    this._view = null;
    if (!chart || !series) return;
    const visible = chart.timeScale().getVisibleRange();
    if (!visible) return;

    const from = String(visible.from);
    const to = String(visible.to);
    const key = `${from}|${to}|${this._source._bars.length}`;
    if (key !== this._cacheKey) {
      this._cacheKey = key;
      const slice = this._source._bars.filter((b) => {
        const t = String(b.time);
        return t >= from && t <= to;
      });
      this._profile = computeVolumeProfile(
        slice,
        this._source._options.bins,
        this._source._options.valuePct,
      );
    }
    const p = this._profile;
    if (!p) return;

    const rows: RowPx[] = [];
    for (let i = 0; i < p.bins.length; i += 1) {
      const b = p.bins[i];
      const yTop = series.priceToCoordinate(b.high);
      const yBottom = series.priceToCoordinate(b.low);
      if (yTop == null || yBottom == null) continue;
      rows.push({
        yTop,
        yBottom,
        buyFrac: b.buy / p.maxBinVolume,
        sellFrac: b.sell / p.maxBinVolume,
        inValueArea: i >= p.valIdx && i <= p.vahIdx,
      });
    }
    this._view = {
      rows,
      pocY: series.priceToCoordinate(p.pocPrice),
      pocPrice: p.pocPrice,
    };
  }

  renderer() {
    return new VolumeProfileRenderer(this._view, this._source._options);
  }
}

export class VolumeProfileIndicator implements ISeriesPrimitive<Time> {
  _bars: VolumeProfileBar[] = [];
  _options: Required<VolumeProfileOptions>;
  private _paneViews: VolumeProfilePaneView[];
  private _chart: IChartApi | undefined;
  private _series: ISeriesApi<keyof SeriesOptionsMap> | undefined;
  private _requestUpdate?: () => void;

  constructor(options: VolumeProfileOptions = {}) {
    this._options = { ...defaults, ...options };
    this._paneViews = [new VolumeProfilePaneView(this)];
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

  setBars(bars: VolumeProfileBar[]) {
    this._bars = bars;
    this._requestUpdate?.();
  }

  updateAllViews() {
    this._paneViews.forEach((v) => v.update());
  }

  paneViews() {
    return this._paneViews;
  }
}
