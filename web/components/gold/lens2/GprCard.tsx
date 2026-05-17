import type { components } from "@/lib/types";

import { Tile } from "../Tile";

type C = components["schemas"]["GoldCyclicalPostureModel"];

function pct(v: string | number | null | undefined): string {
  if (v == null) return "—";
  const n = typeof v === "string" ? Number(v) : v;
  if (!Number.isFinite(n)) return "—";
  return `${(n * 100).toFixed(0)}th`;
}

function fmt(v: string | number | null | undefined, digits = 0): string {
  if (v == null) return "—";
  const n = typeof v === "string" ? Number(v) : v;
  if (!Number.isFinite(n)) return "—";
  return n.toFixed(digits);
}

export function GprCard({ cyclical }: { cyclical: C }) {
  return (
    <Tile
      label="GPR · GEOPOLITICAL"
      value={fmt(cyclical.gpr_value)}
      sub={`52W %ILE ${pct(cyclical.gpr_pct_52w)}`}
    />
  );
}
