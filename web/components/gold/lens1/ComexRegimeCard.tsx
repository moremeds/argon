import type { components } from "@/lib/types";

import { Tile } from "../Tile";

type S = components["schemas"]["GoldStructuralPostureModel"];

function fmt(v: string | number | null | undefined, digits = 0): string {
  if (v == null) return "—";
  const n = typeof v === "string" ? Number(v) : v;
  if (!Number.isFinite(n)) return "—";
  return n.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function ComexRegimeCard({ structural }: { structural: S }) {
  const roc = Number(structural.comex_20d_roc_pct);
  const tone =
    !Number.isFinite(roc) || roc === 0
      ? "default"
      : roc > 0
        ? "positive"
        : "negative";
  const sign = Number.isFinite(roc) && roc > 0 ? "+" : "";
  return (
    <Tile
      label="COMEX REGISTERED · 20D ROC"
      tone={tone}
      value={Number.isFinite(roc) ? `${sign}${(roc * 100).toFixed(1)}%` : "—"}
      sub={`${fmt(structural.comex_registered_oz)} OZ REGISTERED`}
    />
  );
}
