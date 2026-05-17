import type { components } from "@/lib/types";

import { Tile } from "../Tile";

type S = components["schemas"]["GoldStructuralPostureModel"];

function fmt(v: string | number | null | undefined, digits = 2): string {
  if (v == null) return "—";
  const n = typeof v === "string" ? Number(v) : v;
  if (!Number.isFinite(n)) return "—";
  return n.toFixed(digits);
}

export function FxBasketCard({ structural }: { structural: S }) {
  return (
    <Tile
      label="FX BASKET · DXY Z"
      value={fmt(structural.fx_basket_dxy_z)}
      sub={`XAU/CNY premium ${fmt(structural.xau_cny_premium_pct, 3)}`}
    />
  );
}
