// Parity proof for technicalsOverlays: on the frozen real /technicals payloads
// (tests/fixtures/mcp, see its README), every value must deep-equal what the
// chart computed before the extraction — i.e. the same primitives called the
// same way. The concrete literal anchors were computed once from the fixtures
// at authoring time (2026-10-02) and pinned here.
import { describe, expect, it } from "vitest";
import type { TechnicalsResponse } from "@/lib/api";
import {
  computeChanlunFull,
  divergenceTrend,
  type ChanlunBar,
} from "@/lib/chanlun";
import { findFairValueGaps, type FvgBar } from "@/lib/fvg";
import {
  atr,
  bollinger,
  ema,
  highVolMarkers,
  lowVolMarkers,
  volumeMa,
  type VolMarker,
} from "@/lib/indicators";
import {
  buildStats,
  computeVolumeProfile,
  findLvnLevels,
  findSrZones,
} from "@/lib/volumeProfile";
import {
  LOW_VOL_THRESHOLD_PCT,
  technicalsOverlays,
  VOL_MA_PERIOD,
  VP_LOOKBACK,
  type OverlayMarker,
  type TechnicalsOverlays,
} from "@/lib/technicals/overlays";
import { sliceSeriesByTimeframe } from "@/lib/technicals/series";
import aapl from "@/tests/fixtures/mcp/aapl_technicals.json";
import nvda from "@/tests/fixtures/mcp/nvda_technicals.json";
import spy from "@/tests/fixtures/mcp/spy_technicals.json";

const strip = (m: VolMarker): OverlayMarker => ({
  time: m.time,
  position: m.position,
  shape: m.shape,
  text: m.text,
  size: m.size,
});

// What the chart computed before the extraction: the same primitive calls, in
// the same order, with the same constants and filters.
function expected(data: TechnicalsResponse) {
  const full = data.series ?? [];
  const rows = sliceSeriesByTimeframe(full, "1y");
  const closes = full.map((r) => r.close);
  // toAtrBandData's emit rule: sma20 ± 2·ATR(14) only when both exist, ATR > 0.
  const atr14 = atr(
    full.map((r) => r.high),
    full.map((r) => r.low),
    closes,
    14,
  );
  const atrBand = {
    upper: full.map((r, i) => {
      const m = r.sma20;
      const v = atr14[i];
      return m != null && v != null && v > 0 ? m + 2 * v : null;
    }),
    lower: full.map((r, i) => {
      const m = r.sma20;
      const v = atr14[i];
      return m != null && v != null && v > 0 ? m - 2 * v : null;
    }),
  };
  const volMa = volumeMa(
    full.map((r) => r.volume),
    VOL_MA_PERIOD,
  );
  const clBars: ChanlunBar[] = full.flatMap((r) =>
    r.as_of != null && r.high != null && r.low != null && r.close != null
      ? [{ time: r.as_of, high: r.high, low: r.low, close: r.close }]
      : [],
  );
  const chanlun = computeChanlunFull(clBars);
  const vpBars = full.flatMap((r) =>
    r.as_of != null &&
    r.open != null &&
    r.high != null &&
    r.low != null &&
    r.close != null &&
    r.volume != null
      ? [
          {
            time: r.as_of,
            open: r.open,
            high: r.high,
            low: r.low,
            close: r.close,
            volume: r.volume,
          },
        ]
      : [],
  );
  const slice =
    vpBars.length > VP_LOOKBACK ? vpBars.slice(-VP_LOOKBACK) : vpBars;
  const last = slice[slice.length - 1]!;
  const profile = computeVolumeProfile(slice, 60, 70)!;
  const zones = findSrZones(profile, slice, last.close);
  const lvn = findLvnLevels(profile, last.close);
  const fvgBars: FvgBar[] = rows.flatMap((r) =>
    r.as_of != null && r.high != null && r.low != null
      ? [{ time: r.as_of, high: r.high, low: r.low }]
      : [],
  );
  return {
    rows,
    firstAsOf: rows[0]?.as_of ?? "",
    ema5: ema(closes, 5),
    ema20: ema(closes, 20),
    ema50: ema(closes, 50),
    bollinger: bollinger(closes, 20, 2),
    atrBand,
    volMa50: volMa,
    highVol: highVolMarkers(full, { color: "" }).map(strip),
    lowVol: lowVolMarkers(full, volMa, {
      thresholdPct: LOW_VOL_THRESHOLD_PCT,
      color: "",
    }).map(strip),
    clBars,
    chanlun,
    divergenceTrend: divergenceTrend(clBars, chanlun.divergences),
    vp: {
      bars: vpBars,
      window: slice,
      profile,
      zones,
      lvn,
      stats: buildStats(profile, zones, last.close),
    },
    fvg: { bars: fvgBars, gaps: findFairValueGaps(fvgBars) },
  };
}

const CASES: {
  ticker: string;
  fixture: TechnicalsResponse;
  anchors: { ema20Last: number; chanlunPoints: number; vpPoc: number };
}[] = [
  {
    ticker: "AAPL",
    fixture: aapl as unknown as TechnicalsResponse,
    anchors: {
      ema20Last: 325.01683477793944,
      chanlunPoints: 5,
      vpPoc: 254.91644272092208,
    },
  },
  {
    ticker: "NVDA",
    fixture: nvda as unknown as TechnicalsResponse,
    anchors: {
      ema20Last: 218.50341205721912,
      chanlunPoints: 4,
      vpPoc: 183.05068931318914,
    },
  },
  {
    ticker: "SPY",
    fixture: spy as unknown as TechnicalsResponse,
    anchors: {
      ema20Last: 762.8305686924726,
      chanlunPoints: 10,
      vpPoc: 675.1332868347823,
    },
  },
];

describe("technicalsOverlays", () => {
  for (const { ticker, fixture, anchors } of CASES) {
    describe(ticker, () => {
      const o: TechnicalsOverlays = technicalsOverlays(fixture, "1y");
      const x = expected(fixture);

      it("reproduces the window and display cut", () => {
        expect(o.rows).toEqual(x.rows);
        expect(o.firstAsOf).toBe(x.firstAsOf);
      });

      it("reproduces the EMAs, Bollinger and ATR band on full", () => {
        expect(o.ema5).toEqual(x.ema5);
        expect(o.ema20).toEqual(x.ema20);
        expect(o.ema50).toEqual(x.ema50);
        expect(o.bollinger).toEqual(x.bollinger);
        expect(o.atrBand).toEqual(x.atrBand);
      });

      it("reproduces the volume MA50 and vol markers on full", () => {
        expect(o.volMa50).toEqual(x.volMa50);
        expect(o.markers.highVol).toEqual(x.highVol);
        expect(o.markers.lowVol).toEqual(x.lowVol);
      });

      it("reproduces the chanlun structure and divergence trend", () => {
        expect(o.chanlun.bars).toEqual(x.clBars);
        expect(o.chanlun.result).toEqual(x.chanlun);
        expect(o.chanlun.divergenceTrend).toEqual(x.divergenceTrend);
      });

      it("reproduces the volume profile chain on the 360-bar window", () => {
        expect(o.vp.bars).toEqual(x.vp.bars);
        expect(o.vp.window).toEqual(x.vp.window);
        expect(o.vp.profile).toEqual(x.vp.profile);
        expect(o.vp.zones).toEqual(x.vp.zones);
        expect(o.vp.lvn).toEqual(x.vp.lvn);
        expect(o.vp.stats).toEqual(x.vp.stats);
      });

      it("reproduces the FVG set on the windowed rows", () => {
        expect(o.fvg.bars).toEqual(x.fvg.bars);
        expect(o.fvg.gaps).toEqual(x.fvg.gaps);
      });

      it("matches the pinned anchors", () => {
        expect(o.ema20.at(-1)).toBeCloseTo(anchors.ema20Last, 9);
        expect(o.chanlun.result.points.length).toBe(anchors.chanlunPoints);
        expect(o.vp.profile?.pocPrice).toBeCloseTo(anchors.vpPoc, 9);
      });
    });
  }
});
