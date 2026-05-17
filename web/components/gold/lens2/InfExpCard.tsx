import type { components } from "@/lib/types";

import { Tile } from "../Tile";

type C = components["schemas"]["GoldCyclicalPostureModel"];

function fmt(v: string | number | null | undefined, digits = 2): string {
  if (v == null) return "—";
  const n = typeof v === "string" ? Number(v) : v;
  if (!Number.isFinite(n)) return "—";
  return n.toFixed(digits);
}

function pct(v: string | number | null | undefined): string {
  if (v == null) return "—";
  const n = typeof v === "string" ? Number(v) : v;
  if (!Number.isFinite(n)) return "—";
  return `${(n * 100).toFixed(0)}th`;
}

export function InfExpCard({ cyclical }: { cyclical: C }) {
  return (
    <Tile
      label="T5YIFR · INF EXPECTATIONS"
      value={`${fmt(cyclical.t5yifr)}%`}
      sub={`52W %ILE ${pct(cyclical.t5yifr_pct_52w)} · CPI YoY ${fmt(cyclical.cpi_yoy, 1)}%`}
    />
  );
}
