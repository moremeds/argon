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

export function CbReservesCard({ structural }: { structural: S }) {
  return (
    <Tile
      label="CB RESERVES · 12M ACCUM"
      value={`${fmt(structural.cb_strategic_12m_sum_t)} tonnes`}
      sub={
        <>
          STRATEGIC {fmt(structural.cb_strategic_12m_sum_t)} tonnes · TACTICAL{" "}
          {fmt(structural.cb_tactical_12m_sum_t)} tonnes · DIVERSIFIER{" "}
          {fmt(structural.cb_diversifier_12m_sum_t)}
          {" tonnes"}
        </>
      }
    />
  );
}
