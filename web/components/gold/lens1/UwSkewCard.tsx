import type { components } from "@/lib/types";

import { Tile } from "../Tile";
import { PersistOnlyBadge } from "../chips/PersistOnlyBadge";

type S = components["schemas"]["GoldStructuralPostureModel"];

export function UwSkewCard({ structural }: { structural: S }) {
  const sigma = structural.uw_25d_skew_sigma;
  return (
    <Tile
      label="UW 25Δ SKEW"
      value={sigma == null ? "—" : `${sigma}σ`}
      sub={<PersistOnlyBadge />}
    />
  );
}
