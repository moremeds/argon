import type { components } from "@/lib/types";

import { Tile } from "../Tile";

type C = components["schemas"]["GoldCyclicalPostureModel"];

function fmt(v: string | number | null | undefined, digits = 2): string {
  if (v == null) return "—";
  const n = typeof v === "string" ? Number(v) : v;
  if (!Number.isFinite(n)) return "—";
  return n.toFixed(digits);
}

export function UsdTrendCard({ cyclical }: { cyclical: C }) {
  return (
    <Tile
      label="DXY · USD TREND"
      value={fmt(cyclical.dxy)}
      sub={`60D σ ${fmt(cyclical.dxy_60d_sigma)}`}
    />
  );
}
