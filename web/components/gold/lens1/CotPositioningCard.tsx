import type { components } from "@/lib/types";

import { Tile } from "../Tile";
import { HeuristicBadge } from "../chips/HeuristicBadge";

type S = components["schemas"]["GoldStructuralPostureModel"];

function pct(v: string | number | null | undefined): string {
  if (v == null) return "—";
  const n = typeof v === "string" ? Number(v) : v;
  if (!Number.isFinite(n)) return "—";
  return `${(n * 100).toFixed(0)}th`;
}

export function CotPositioningCard({ structural }: { structural: S }) {
  return (
    <Tile
      label="COT MM NET · 5Y %ILE"
      value={pct(structural.cot_mm_net_pct)}
      sub={
        <span style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <HeuristicBadge reason="release-lagged, T+3 enforced" />
          Δ4W {structural.cot_mm_4w_change_sigma ?? "—"}σ
        </span>
      }
    />
  );
}
