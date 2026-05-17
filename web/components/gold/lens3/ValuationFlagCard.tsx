import type { components } from "@/lib/types";

import { Tile } from "../Tile";

type V = components["schemas"]["GoldValuationPostureModel"];

function pct(v: string | number | null | undefined): string {
  if (v == null) return "—";
  const n = typeof v === "string" ? Number(v) : v;
  if (!Number.isFinite(n)) return "—";
  return `${(n * 100).toFixed(0)}th`;
}

const flagTone: Record<
  string,
  "default" | "positive" | "warning" | "negative"
> = {
  Low: "positive",
  Moderate: "default",
  High: "warning",
  Severe: "negative",
};

export function ValuationFlagCard({ valuation }: { valuation: V }) {
  const tone = flagTone[valuation.flag] ?? "default";
  return (
    <Tile
      label="REAL PRICE · MEAN-REVERSION FLAG"
      tone={tone}
      value={valuation.flag.toUpperCase()}
      sub={
        <>
          GOLD/CPI {pct(valuation.real_price_percentile)} · GOLD/M2{" "}
          {pct(valuation.gold_m2_ratio_percentile)} · GOLD/SPX{" "}
          {pct(valuation.gold_spx_ratio_percentile)}
        </>
      }
    />
  );
}
