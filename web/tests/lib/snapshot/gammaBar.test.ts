// gammaBar — oracle is the pre-move derivation block from MagnetGammaBar.tsx,
// pinned on all three frozen *_stock.json payloads plus literal branch cases.
import { describe, expect, it } from "vitest";
import type { components } from "@/lib/types";
import { toNum } from "@/lib/formatters";
import { gammaBarTiles } from "@/lib/snapshot/gammaBar";
import aapl from "@/tests/fixtures/mcp/aapl_stock.json";
import nvda from "@/tests/fixtures/mcp/nvda_stock.json";
import spy from "@/tests/fixtures/mcp/spy_stock.json";

type Report = components["schemas"]["SingleStockReport"];

const STOCK = {
  AAPL: aapl as unknown as Report,
  NVDA: nvda as unknown as Report,
  SPY: spy as unknown as Report,
};

// Pre-move oracle: verbatim from MagnetGammaBar.
function oracle(report: Report) {
  const regime = report.dealer_regime;
  const spot = toNum(report.market_structure?.spot);
  const netGex = toNum(report.market_structure?.net_gex);
  const prevClose = toNum(regime?.prev_close_net_gex);
  const odte = toNum(regime?.odte_net_gex);
  const lv = report.market_structure_levels;
  const callWall = lv?.call_wall ? toNum(lv.call_wall.strike) : null;
  const callWallGex = lv?.call_wall ? toNum(lv.call_wall.net_gex) : null;
  const putWall = lv?.put_wall ? toNum(lv.put_wall.strike) : null;
  const putWallGex = lv?.put_wall ? toNum(lv.put_wall.net_gex) : null;
  const flip = lv?.gex_flip ? toNum(lv.gex_flip.strike) : null;
  const useCallTop =
    (callWallGex != null ? Math.abs(callWallGex) : 0) >=
    (putWallGex != null ? Math.abs(putWallGex) : 0);
  const topWallStrike = useCallTop ? callWall : putWall;
  const topWallGex = useCallTop ? callWallGex : putWallGex;
  const deltaVsPrev =
    netGex != null && prevClose != null ? netGex - prevClose : null;
  const deltaPct =
    netGex != null && prevClose != null && prevClose !== 0
      ? deltaVsPrev! / Math.abs(prevClose)
      : null;
  const flipDistPct =
    flip != null && spot != null && spot > 0 ? (flip - spot) / spot : null;
  return {
    spot,
    netGex,
    prevClose,
    odte,
    callWall,
    callWallGex,
    putWall,
    putWallGex,
    flip,
    topWallStrike,
    topWallGex,
    deltaVsPrev,
    deltaPct,
    flipDistPct,
  };
}

describe("gammaBarTiles on frozen stock payloads", () => {
  it.each(Object.entries(STOCK))("%s equals the pre-move oracle", (_t, rep) => {
    expect(gammaBarTiles(rep)).toEqual(oracle(rep));
  });

  it("pins AAPL literals", () => {
    const g = gammaBarTiles(STOCK.AAPL);
    expect(g.netGex).toBeCloseTo(85013.2902, 4);
    expect(g.deltaVsPrev).toBeCloseTo(-1426038.8108, 4);
    expect(g.deltaPct).toBeCloseTo(-0.9437390079774622, 12);
    expect(g.topWallStrike).toBe(340);
    expect(g.topWallGex).toBeCloseTo(42547.6316, 4);
    expect(g.flip).toBe(320);
    expect(g.flipDistPct).toBeCloseTo(-0.05290418054014059, 12);
    expect(g.odte).toBeNull(); // fixture's dealer_regime has no odte_net_gex
  });

  it("pins NVDA and SPY literals", () => {
    const n = gammaBarTiles(STOCK.NVDA);
    expect(n.topWallStrike).toBe(220);
    expect(n.flipDistPct).toBeCloseTo(-0.04111479332827508, 12);
    const s = gammaBarTiles(STOCK.SPY);
    expect(s.netGex).toBeCloseTo(38429.9798, 4);
    expect(s.topWallStrike).toBe(770);
    expect(s.flip).toBe(757);
    expect(s.flipDistPct).toBeCloseTo(-0.01658924309719048, 12);
  });
});

describe("gammaBarTiles edge branches", () => {
  const base = {
    market_structure: { spot: "100", net_gex: "10" },
    dealer_regime: { prev_close_net_gex: "0", odte_net_gex: null },
    market_structure_levels: {
      call_wall: { strike: "105", net_gex: "-50" },
      put_wall: { strike: "95", net_gex: "50" },
      gex_flip: { strike: "102", net_gex: "0" },
    },
  } as unknown as Report;

  it("prev close 0 → deltaPct null (no division by zero)", () => {
    const g = gammaBarTiles(base);
    expect(g.deltaVsPrev).toBe(10);
    expect(g.deltaPct).toBeNull();
  });

  it("|call| = |put| ties go to the call wall", () => {
    const g = gammaBarTiles(base);
    expect(g.topWallStrike).toBe(105);
    expect(g.topWallGex).toBe(-50);
  });

  it("larger |put| wins the wall", () => {
    const g = gammaBarTiles({
      ...base,
      market_structure_levels: {
        call_wall: { strike: "105", net_gex: "-40" },
        put_wall: { strike: "95", net_gex: "60" },
      },
    } as unknown as Report);
    expect(g.topWallStrike).toBe(95);
  });

  it("flip distance nulls when flip or spot is unusable", () => {
    const noFlip = gammaBarTiles({ ...base, market_structure_levels: {} } as Report);
    expect(noFlip.flip).toBeNull();
    expect(noFlip.flipDistPct).toBeNull();
    const badSpot = gammaBarTiles({
      ...base,
      market_structure: { spot: "0", net_gex: "10" },
    } as unknown as Report);
    expect(badSpot.flipDistPct).toBeNull();
  });
});
