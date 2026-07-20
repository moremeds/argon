/**
 * Volume profile drawn against the right edge of the price pane — horizontal
 * bars growing leftward, buy volume hugging the axis, sell volume stacked
 * outside it. Same attach/paneViews lifecycle as lib/lwc/chanlunZhongshu.ts;
 * the binning math lives in lib/volumeProfile.ts.
 *
 * FIXED window (the most recent `lookback` bars), NOT the visible range. This
 * shipped as visible-range first and that was wrong: panning between ~150 and
 * ~600 visible bars moves the POC by a median of 11.6 ATR, so the levels were
 * substantially a function of the viewport. 360 sessions is the measured
 * compromise — long enough that the histogram is steady, short enough that the
 * levels stay within ~10–20% of spot instead of anchoring to prices the market
 * has left behind (a 5-year window puts the POC 35–92% below spot).
 * Study: docs/research/2026-07-20-volume-profile-window-study.md
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
  findLvnLevels,
  findSrZones,
  type SrZone,
  type VolumeProfile,
  type VpBar,
} from "@/lib/volumeProfile";

export type VolumeProfileBar = VpBar & { time: Time };

/** What the profile currently says — pushed to React for the stats readout. */
export type VolumeProfileStats = {
  poc: number;
  vah: number;
  val: number;
  nearestSupport: number | null;
  nearestResistance: number | null;
  bias: "bullish" | "bearish" | "balanced";
  supportCount: number;
  resistanceCount: number;
  lastPrice: number;
};

export interface VolumeProfileOptions {
  buyColor?: string;
  sellColor?: string;
  pocColor?: string;
  supportColor?: string;
  resistanceColor?: string;
  lvnColor?: string;
  labelColor?: string;
  bins?: number;
  valuePct?: number;
  /** Sessions the profile covers, counted back from the newest bar. */
  lookback?: number;
  /** Profile width as a fraction of pane width, clamped by min/max px. */
  widthFrac?: number;
  minWidthPx?: number;
  maxWidthPx?: number;
  showZones?: boolean;
  showLvn?: boolean;
  onStats?: (stats: VolumeProfileStats | null) => void;
}

const defaults: Required<Omit<VolumeProfileOptions, "onStats">> = {
  buyColor: "rgba(0, 137, 123, 0.85)",
  sellColor: "rgba(156, 39, 176, 0.85)",
  pocColor: "rgba(255, 167, 38, 0.9)",
  supportColor: "rgba(38, 166, 154, 1)",
  resistanceColor: "rgba(255, 82, 82, 1)",
  lvnColor: "rgba(140, 140, 150, 0.75)",
  labelColor: "rgba(240, 240, 245, 0.95)",
  bins: 60,
  valuePct: 70,
  lookback: 360,
  widthFrac: 0.22,
  minWidthPx: 70,
  maxWidthPx: 240,
  showZones: true,
  showLvn: true,
};

type RowPx = {
  yTop: number;
  yBottom: number;
  buyFrac: number; // 0..1 of the profile width
  sellFrac: number;
  inValueArea: boolean;
};

type ZonePx = {
  yTop: number;
  yBottom: number;
  support: boolean;
  label: string;
};

type ViewPx = {
  rows: RowPx[];
  pocY: number | null;
  pocPrice: number;
  zones: ZonePx[];
  lvn: { y: number; price: number }[];
};

function buildStats(
  profile: VolumeProfile,
  zones: readonly SrZone[],
  lastPrice: number,
): VolumeProfileStats {
  const vah = profile.bins[profile.vahIdx].high;
  const val = profile.bins[profile.valIdx].low;
  const supports = zones.filter((z) => z.side === "support");
  const resistances = zones.filter((z) => z.side === "resistance");
  return {
    poc: profile.pocPrice,
    vah,
    val,
    // Nearest = the one price would reach first, so highest support / lowest
    // resistance.
    nearestSupport: supports.length
      ? Math.max(...supports.map((z) => z.price))
      : null,
    nearestResistance: resistances.length
      ? Math.min(...resistances.map((z) => z.price))
      : null,
    bias:
      lastPrice > vah ? "bullish" : lastPrice < val ? "bearish" : "balanced",
    supportCount: supports.length,
    resistanceCount: resistances.length,
    lastPrice,
  };
}

class VolumeProfileRenderer implements IPrimitivePaneRenderer {
  constructor(
    private _view: ViewPx | null,
    private _options: Required<Omit<VolumeProfileOptions, "onStats">>,
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
      ctx.font = "10px monospace";

      // S/R bands span the full pane — they are levels in price, not in time.
      for (const z of view.zones) {
        const hue = z.support
          ? this._options.supportColor
          : this._options.resistanceColor;
        const h = Math.max(1, z.yBottom - z.yTop);
        ctx.globalAlpha = 0.12;
        ctx.fillStyle = hue;
        ctx.fillRect(0, z.yTop, right, h);
        ctx.globalAlpha = 0.7;
        ctx.strokeStyle = hue;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(0, z.yTop);
        ctx.lineTo(right, z.yTop);
        ctx.moveTo(0, z.yBottom);
        ctx.lineTo(right, z.yBottom);
        ctx.stroke();
        // Label sits just left of the profile band so the two never collide.
        ctx.globalAlpha = 1;
        ctx.fillStyle = hue;
        ctx.textAlign = "right";
        ctx.textBaseline = "middle";
        ctx.fillText(z.label, right - width - 6, (z.yTop + z.yBottom) / 2);
      }
      ctx.textAlign = "left";

      // Long dashes, not the grid's short dots — a faint 4/4 dash reads as
      // chart furniture and the level disappears into the background.
      ctx.globalAlpha = 0.9;
      ctx.strokeStyle = this._options.lvnColor;
      ctx.setLineDash([10, 5]);
      ctx.textAlign = "right";
      ctx.textBaseline = "middle";
      for (const l of view.lvn) {
        ctx.beginPath();
        ctx.moveTo(0, l.y);
        ctx.lineTo(right, l.y);
        ctx.stroke();
        ctx.fillStyle = this._options.lvnColor;
        ctx.fillText(`LVN ${l.price.toFixed(2)}`, right - width - 6, l.y);
      }
      ctx.setLineDash([]);
      ctx.textAlign = "left";

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
  private _zones: SrZone[] = [];
  private _lvn: number[] = [];

  constructor(private _source: VolumeProfileIndicator) {}

  update() {
    const series = this._source.seriesApi();
    this._view = null;
    if (!series) return;

    const opts = this._source._options;
    const all = this._source._bars;
    // The most recent `lookback` sessions — independent of scroll and zoom, so
    // panning can no longer move the levels.
    const slice = all.length > opts.lookback ? all.slice(-opts.lookback) : all;
    const key = slice.length
      ? `${slice.length}|${String(slice[0].time)}|${String(slice[slice.length - 1].time)}`
      : "empty";
    // Re-bin only when the underlying bars actually changed: updateAllViews()
    // fires on every crosshair move and every pan, and the stats callback must
    // not re-fire with them.
    if (key !== this._cacheKey) {
      this._cacheKey = key;
      this._profile = computeVolumeProfile(slice, opts.bins, opts.valuePct);
      const last = slice[slice.length - 1];
      if (this._profile && last) {
        this._zones = opts.showZones
          ? findSrZones(this._profile, slice, last.close)
          : [];
        this._lvn = opts.showLvn
          ? findLvnLevels(this._profile, last.close)
          : [];
        this._source._emitStats(
          buildStats(this._profile, this._zones, last.close),
        );
      } else {
        this._zones = [];
        this._lvn = [];
        this._source._emitStats(null);
      }
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
    const zones: ZonePx[] = [];
    for (const z of this._zones) {
      const yTop = series.priceToCoordinate(z.price + z.halfWidth);
      const yBottom = series.priceToCoordinate(z.price - z.halfWidth);
      if (yTop == null || yBottom == null) continue;
      zones.push({
        yTop,
        yBottom,
        support: z.side === "support",
        label:
          `${z.side === "support" ? "S" : "R"} ${z.price.toFixed(2)} · ${z.strength}%` +
          (z.touches > 1 ? ` ×${z.touches}` : ""),
      });
    }
    const lvn = this._lvn.flatMap((price) => {
      const y = series.priceToCoordinate(price);
      return y == null ? [] : [{ y, price }];
    });

    this._view = {
      rows,
      pocY: series.priceToCoordinate(p.pocPrice),
      pocPrice: p.pocPrice,
      zones,
      lvn,
    };
  }

  renderer() {
    return new VolumeProfileRenderer(this._view, this._source._options);
  }
}

export class VolumeProfileIndicator implements ISeriesPrimitive<Time> {
  _bars: VolumeProfileBar[] = [];
  _options: Required<Omit<VolumeProfileOptions, "onStats">>;
  private _onStats?: (stats: VolumeProfileStats | null) => void;
  private _paneViews: VolumeProfilePaneView[];
  private _chart: IChartApi | undefined;
  private _series: ISeriesApi<keyof SeriesOptionsMap> | undefined;
  private _requestUpdate?: () => void;

  constructor({ onStats, ...options }: VolumeProfileOptions = {}) {
    this._options = { ...defaults, ...options };
    this._onStats = onStats;
    this._paneViews = [new VolumeProfilePaneView(this)];
  }

  /**
   * Fired only when the visible range actually changed, so this never loops
   * back through React on a crosshair move. Deferred a tick because
   * updateAllViews() runs inside lightweight-charts' render pass — a synchronous
   * setState there would be a render-phase update.
   */
  _emitStats(stats: VolumeProfileStats | null) {
    const cb = this._onStats;
    if (cb) queueMicrotask(() => cb(stats));
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
