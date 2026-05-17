import type { components } from "@/lib/types";

import { Tile } from "../Tile";

type Spot = components["schemas"]["GoldSpotTile"];

function fmt(v: string | number, digits = 2): string {
  const n = typeof v === "string" ? Number(v) : v;
  if (!Number.isFinite(n)) return "—";
  return n.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function SpotPriceCard({ spot }: { spot: Spot }) {
  const deltaAbs = Number(spot.delta_abs);
  const deltaPct = Number(spot.delta_pct);
  const tone =
    deltaAbs > 0 ? "positive" : deltaAbs < 0 ? "negative" : "default";
  const sign = deltaAbs > 0 ? "+" : "";
  return (
    <Tile
      label="GLD ETF · USD"
      tone={tone}
      value={fmt(spot.last)}
      sub={
        <>
          {sign}
          {fmt(spot.delta_abs)} ({sign}
          {fmt(deltaPct * 100, 2)}%) · H {fmt(spot.high)} · L {fmt(spot.low)}
        </>
      }
    />
  );
}
