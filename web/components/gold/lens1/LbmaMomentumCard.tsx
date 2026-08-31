import type { components } from "@/lib/types";

import { Tile } from "../Tile";

type S = components["schemas"]["GoldStructuralPostureModel"];

/**
 * Board t5, "Western institutional flows · L1 detail" — the LBMA row.
 *
 * `structural.lbma_30d_momentum_t` arrives on every posture response and was rendered by
 * nothing until 2026-08-29. The board lists it beside GLD holdings as the second of the
 * two vault series that "doubly confirm" a western return, which is the whole reason it
 * is on the panel: one custodian moving is a flow, two moving together is a direction.
 */
export function LbmaMomentumCard({ structural }: { structural: S }) {
  const raw = structural.lbma_30d_momentum_t;
  const n = raw == null ? null : Number(raw);
  const known = n !== null && Number.isFinite(n);
  const sign = !known
    ? ""
    : (n as number) > 0
      ? "+"
      : (n as number) < 0
        ? "−"
        : "";
  return (
    <Tile
      label="LBMA · 30D MOMENTUM"
      tone={!known ? "default" : (n as number) >= 0 ? "positive" : "negative"}
      value={
        known
          ? `${sign}${Math.abs(n as number).toLocaleString(undefined, {
              minimumFractionDigits: 1,
              maximumFractionDigits: 1,
            })}t`
          : "—"
      }
      sub={
        known ? "VAULT INVENTORY, 30D CHANGE" : "NOT READ FOR THIS OBSERVATION"
      }
    />
  );
}
