/**
 * Horizontal density histogram anchored at one point on the time axis — the
 * "what does the model think tomorrow's close looks like" profile.
 *
 * Same attach/paneViews lifecycle as lib/lwc/chanlunZhongshu.ts. Deliberately NOT a
 * reuse of lib/lwc/volumeProfile.ts: that one bins observed volume against the right
 * edge of the pane and carries POC/value-area/SR machinery this has no use for. Here
 * the bars are simulated probability mass, they hang off a specific forecast date, and
 * there is no "point of control" to mark — the median is published separately.
 *
 * Bars are fed in PRICE space (already converted from the model's cumulative-return
 * units by the caller) so the primitive never needs to know the anchor close.
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

export interface DensityBar {
  lower: number; // price at the bottom edge of the bin
  upper: number; // price at the top edge
  weight: number; // 0..1, share of the peak bin (NOT of total mass)
}

export interface DensityProfileData {
  time: Time; // x anchor — the forecast date this profile belongs to
  bars: DensityBar[];
  splitPrice?: number; // bins above use upColor, below downColor (normally the anchor close)
}

export interface DensityProfileOptions {
  upColor?: string;
  downColor?: string;
  maxWidthPx?: number;
  /** Grow to the right of the anchor date (default) or to the left. */
  direction?: "right" | "left";
  /** Where the flat baseline sits: on the profile's own `time` (default), or flush
   *  against the right price axis regardless of date — the TradingView volume-profile
   *  idiom, which reads as "this is the distribution", not "this happens on that bar".
   *  With "pane-right" the `time` field is ignored. */
  anchor?: "time" | "pane-right";
  /** "curve" draws one filled silhouette through the bin tops (the reference look);
   *  "bars" draws each bin as a discrete rectangle. */
  style?: "curve" | "bars";
  lineColor?: string;
}

const defaults: Required<DensityProfileOptions> = {
  upColor: "rgba(239, 83, 80, 0.55)",
  downColor: "rgba(38, 166, 154, 0.55)",
  maxWidthPx: 90,
  direction: "right",
  anchor: "time",
  style: "curve",
  lineColor: "rgba(226, 232, 240, 0.55)",
};

type BarPx = { x: number; y: number; w: number; h: number; color: string };

class DensityProfileRenderer implements IPrimitivePaneRenderer {
  constructor(
    private _bars: BarPx[],
    private _opts: Required<DensityProfileOptions>,
  ) {}
  draw() {}
  // Background pass: the profile sits BEHIND candles and cone bands so it never
  // obscures price. It is context, not the subject.
  drawBackground(target: CanvasRenderingTarget2D) {
    if (this._bars.length === 0) return;
    target.useBitmapCoordinateSpace((scope) => {
      const ctx = scope.context;
      ctx.scale(scope.horizontalPixelRatio, scope.verticalPixelRatio);
      if (this._opts.style === "bars") {
        for (const b of this._bars) {
          if (!(b.w > 0) || !Number.isFinite(b.h)) continue;
          ctx.fillStyle = b.color;
          ctx.fillRect(b.x, b.y, b.w, b.h);
        }
        return;
      }
      this._drawCurve(ctx);
    });
  }

  /** Filled silhouette: up the baseline, back down through the bin tops. Split into
   *  above/below runs so the two-tone colouring survives, with a single outline over
   *  the whole shape so the seam between them is invisible. */
  private _drawCurve(ctx: CanvasRenderingContext2D) {
    const bars = this._bars;
    const x0 =
      this._opts.direction === "right" ? bars[0].x : bars[0].x + bars[0].w;
    const tip = (b: BarPx) =>
      this._opts.direction === "right" ? b.x + b.w : b.x;

    let run: BarPx[] = [];
    // Tracked explicitly rather than read off run[0]: the boundary bin is carried
    // into the NEXT run so the two fills abut with no seam, which makes run[0] the
    // previous run's colour. Deriving the fill from it painted every segment in the
    // first segment's colour (the whole silhouette came out teal).
    let runColor = bars[0].color;
    const flush = () => {
      if (run.length === 0) return;
      ctx.beginPath();
      ctx.moveTo(x0, run[0].y);
      for (const b of run) ctx.lineTo(tip(b), b.y + b.h / 2);
      ctx.lineTo(x0, run[run.length - 1].y + run[run.length - 1].h);
      ctx.closePath();
      ctx.fillStyle = runColor;
      ctx.fill();
      run = [];
    };
    for (const b of bars) {
      if (run.length && b.color !== run[run.length - 1].color) {
        const boundary = run[run.length - 1];
        flush();
        runColor = b.color;
        run.push(boundary);
      }
      run.push(b);
    }
    flush();

    ctx.beginPath();
    ctx.moveTo(x0, bars[0].y);
    for (const b of bars) ctx.lineTo(tip(b), b.y + b.h / 2);
    ctx.lineTo(x0, bars[bars.length - 1].y + bars[bars.length - 1].h);
    ctx.strokeStyle = this._opts.lineColor;
    ctx.lineWidth = 1;
    ctx.stroke();
  }
}

class DensityProfilePaneView implements IPrimitivePaneView {
  _bars: BarPx[] = [];
  constructor(private _source: DensityProfile) {}

  update() {
    this._bars = [];
    const chart = this._source.chartApi();
    const series = this._source.seriesApi();
    const data = this._source._data;
    if (!chart || !series || !data || data.bars.length === 0) return;

    const opts = this._source._options;
    // timeScale().width() is the drawing area in media coords — i.e. exactly where the
    // price axis starts — so "pane-right" needs no ResizeObserver of its own.
    const x0 =
      opts.anchor === "pane-right"
        ? chart.timeScale().width()
        : chart.timeScale().timeToCoordinate(data.time);
    if (x0 == null) return; // profile date scrolled off-screen

    const peak = Math.max(...data.bars.map((b) => b.weight));
    if (!(peak > 0)) return;

    for (const b of data.bars) {
      const yTop = series.priceToCoordinate(b.upper);
      const yBot = series.priceToCoordinate(b.lower);
      if (yTop == null || yBot == null) continue;
      const w = (b.weight / peak) * opts.maxWidthPx;
      // +0.5 keeps adjacent bins visually contiguous instead of hairline-gapped
      const h = Math.max(1, yBot - yTop + 0.5);
      const above =
        data.splitPrice == null || (b.lower + b.upper) / 2 >= data.splitPrice;
      this._bars.push({
        x: opts.direction === "right" ? x0 : x0 - w,
        y: yTop,
        w,
        h,
        color: above ? opts.upColor : opts.downColor,
      });
    }
  }

  renderer() {
    return new DensityProfileRenderer(this._bars, this._source._options);
  }
}

export class DensityProfile implements ISeriesPrimitive<Time> {
  _data: DensityProfileData | null = null;
  _options: Required<DensityProfileOptions>;
  private _paneViews: DensityProfilePaneView[];
  private _chart: IChartApi | undefined;
  private _series: ISeriesApi<keyof SeriesOptionsMap> | undefined;
  private _requestUpdate?: () => void;

  constructor(options: DensityProfileOptions = {}) {
    this._options = { ...defaults, ...options };
    this._paneViews = [new DensityProfilePaneView(this)];
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

  setProfile(data: DensityProfileData | null) {
    this._data = data;
    this._requestUpdate?.();
  }

  updateAllViews() {
    this._paneViews.forEach((v) => v.update());
  }

  paneViews() {
    return this._paneViews;
  }
}

/**
 * Histogram counts (cumulative-return space, from the API) -> price-space bars.
 *
 * Weights are normalised to the PEAK bin, not to total mass: the renderer scales bar
 * length by weight, and normalising to the sum would make a 64-bin profile render as 64
 * invisible slivers.
 */
export function densityBarsFromBins(
  bins: { lo: number; hi: number; n_bins: number; counts: number[] },
  anchorClose: number,
): DensityBar[] {
  const width = (bins.hi - bins.lo) / bins.n_bins;
  if (!(width > 0)) return [];
  const peak = Math.max(...bins.counts);
  if (!(peak > 0)) return [];
  return bins.counts.map((c, i) => ({
    lower: anchorClose * (1 + bins.lo + i * width),
    upper: anchorClose * (1 + bins.lo + (i + 1) * width),
    weight: c / peak,
  }));
}
