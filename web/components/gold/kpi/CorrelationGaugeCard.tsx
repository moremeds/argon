import type { components } from "@/lib/types";

import { Tile } from "../Tile";

type Gauge = components["schemas"]["GoldGaugeState"];

function fmt(v: string | number | null | undefined): string {
  if (v == null) return "—";
  const n = typeof v === "string" ? Number(v) : v;
  if (!Number.isFinite(n)) return "—";
  return n.toFixed(2);
}

export function CorrelationGaugeCard({ gauge }: { gauge: Gauge }) {
  const tone =
    gauge.state === "operative"
      ? "positive"
      : gauge.state === "suspended"
        ? "warning"
        : "default";
  return (
    <Tile
      label="GOLD ↔ DFII10 · 252D"
      tone={tone}
      value={fmt(gauge.corr_252d)}
      sub={
        <>
          60D {fmt(gauge.corr_60d)} · 126D {fmt(gauge.corr_126d)} · 504D{" "}
          {fmt(gauge.corr_504d)}
        </>
      }
    />
  );
}
