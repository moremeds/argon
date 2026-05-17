import type { components } from "@/lib/types";

import { Tile } from "../Tile";

type C = components["schemas"]["GoldCyclicalPostureModel"];

function fmt(v: string | number | null | undefined, digits = 2): string {
  if (v == null) return "—";
  const n = typeof v === "string" ? Number(v) : v;
  if (!Number.isFinite(n)) return "—";
  return n.toFixed(digits);
}

export function RealRateCard({ cyclical }: { cyclical: C }) {
  const chg = Number(cyclical.dfii10_60d_change_bps);
  const tone =
    !Number.isFinite(chg) || chg === 0
      ? "default"
      : chg > 0
        ? "negative"
        : "positive";
  return (
    <Tile
      label="DFII10 · REAL RATE"
      tone={tone}
      value={`${fmt(cyclical.dfii10)}%`}
      sub={
        Number.isFinite(chg)
          ? `60D ${chg > 0 ? "+" : ""}${chg.toFixed(0)} BPS`
          : "60D —"
      }
    />
  );
}
