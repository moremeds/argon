// Gamma-bar derivations, verbatim from components/stock/panels/MagnetGammaBar.tsx.
// The component still owns the dealer_regime early-return; this function
// returns nulls for regime-sourced fields when the payload lacks them.
import { toNum } from "@/lib/formatters";
import type { components } from "@/lib/types";

export type GammaBarReport = components["schemas"]["SingleStockReport"];

export function gammaBarTiles(report: GammaBarReport) {
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

  // Top wall = larger |gex|; ties go to the call wall.
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
