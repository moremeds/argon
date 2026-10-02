// Parity proof for the magnet tile prep moved into lib/magnetTiles.ts: on the
// frozen real /magnets payloads (tests/fixtures/mcp, see its README), the new
// functions must deep-equal what MagnetSubTab computed inline before the
// extraction — the same expressions copied below as the oracle. Literal
// anchors were computed once from the fixtures at authoring time (2026-10-02).
import { describe, expect, it } from "vitest";
import type { MagnetsResponse } from "@/lib/api";
import {
  kinematicsLeg,
  sma,
  velocity,
  volumeTile,
} from "@/lib/magnetTiles";
import aapl from "@/tests/fixtures/mcp/aapl_magnets.json";
import nvda from "@/tests/fixtures/mcp/nvda_magnets.json";
import spy from "@/tests/fixtures/mcp/spy_magnets.json";

const VOL_BARS = 34;
const KIN = 5;

// The pre-extraction MagnetSubTab tile prep, verbatim: 34-bar volume slice,
// SMA20 of volume over all candles then sliced, last vol + ratio, and the
// KIN=5 velocity/acceleration leg.
function expected(data: MagnetsResponse) {
  const volBars = data.candles.slice(-VOL_BARS).map((c) => ({
    volume: c.volume,
    up: c.close >= c.open,
  }));
  const volMa = sma(
    data.candles.map((c) => c.volume),
    20,
  ).slice(-VOL_BARS);
  const lastVol = data.candles.at(-1)?.volume ?? null;
  const lastVolMa = volMa.at(-1) ?? null;
  const ratio =
    lastVol != null && lastVolMa ? lastVol / lastVolMa : null;
  const closes = data.candles.map((c) => c.close);
  const n = closes.length;
  const v = velocity(closes, n - 1 - KIN, n - 1);
  const vPrev = velocity(closes, n - 1 - 2 * KIN, n - 1 - KIN);
  const accel = v != null && vPrev != null ? (v - vPrev) / KIN : null;
  return {
    vol: { bars: volBars, ma: volMa, lastVol, lastVolMa, ratio },
    kin: { v, accel },
  };
}

const CASES: {
  ticker: string;
  fixture: MagnetsResponse;
  anchors: { lastVol: number; ratio: number; v: number; accel: number };
}[] = [
  {
    ticker: "AAPL",
    fixture: aapl as unknown as MagnetsResponse,
    anchors: {
      lastVol: 86249183,
      ratio: 1.9842766978754092,
      v: 0.23126898469907342,
      accel: -0.002983688016722219,
    },
  },
  {
    ticker: "NVDA",
    fixture: nvda as unknown as MagnetsResponse,
    anchors: {
      lastVol: 189073342,
      ratio: 1.4042912963375256,
      v: 0.3620218239446471,
      accel: 0.25355068381973656,
    },
  },
  {
    ticker: "SPY",
    fixture: spy as unknown as MagnetsResponse,
    anchors: {
      lastVol: 73943400,
      ratio: 1.7897542411422012,
      v: -0.06812977175206791,
      accel: 0.032527304469156526,
    },
  },
];

describe("magnet tile prep", () => {
  for (const { ticker, fixture, anchors } of CASES) {
    describe(ticker, () => {
      const x = expected(fixture);

      it("reproduces the volume tile", () => {
        const vol = volumeTile(fixture.candles);
        expect(vol).toEqual(x.vol);
      });

      it("reproduces the kinematics leg", () => {
        expect(kinematicsLeg(fixture.candles.map((c) => c.close))).toEqual(
          x.kin,
        );
      });

      it("matches the pinned anchors", () => {
        const vol = volumeTile(fixture.candles);
        const kin = kinematicsLeg(fixture.candles.map((c) => c.close));
        expect(vol.lastVol).toBe(anchors.lastVol);
        expect(vol.ratio).toBeCloseTo(anchors.ratio, 12);
        expect(kin.v).toBeCloseTo(anchors.v, 12);
        expect(kin.accel).toBeCloseTo(anchors.accel, 12);
      });
    });
  }

  it("degenerates cleanly on short inputs", () => {
    const vol = volumeTile([]);
    expect(vol.bars).toEqual([]);
    expect(vol.lastVol).toBeNull();
    expect(vol.ratio).toBeNull();
    const kin = kinematicsLeg([10, 11, 12]);
    expect(kin).toEqual({ v: null, accel: null });
  });
});
