import type { components } from "@/lib/types";

import { Tile } from "../Tile";

type S = components["schemas"]["GoldStructuralPostureModel"];

function fmt(v: string | number | null | undefined, digits = 1): string {
  if (v == null) return "—";
  const n = typeof v === "string" ? Number(v) : v;
  if (!Number.isFinite(n)) return "—";
  return n.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function EtfFlowCard({ structural }: { structural: S }) {
  const flow = Number(structural.gld_30d_net_flow_t);
  const tone =
    !Number.isFinite(flow) || flow === 0
      ? "default"
      : flow > 0
        ? "positive"
        : "negative";
  const sign = Number.isFinite(flow) && flow > 0 ? "+" : "";
  return (
    <Tile
      label="GLD FLOW · 30D NET"
      tone={tone}
      value={`${sign}${fmt(structural.gld_30d_net_flow_t)} T`}
      sub={`GLD ${fmt(structural.gld_holdings_t)} T held`}
    />
  );
}
