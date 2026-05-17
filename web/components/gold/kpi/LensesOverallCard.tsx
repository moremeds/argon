import type { components } from "@/lib/types";

import { Tile } from "../Tile";
import { PostureChip, type PostureState } from "../chips/PostureChip";

type State = components["schemas"]["GoldStateResponse"];

export function LensesOverallCard({ state }: { state: State }) {
  const chips: [string, PostureState][] = [
    ["L1", state.structural.posture_chip as PostureState],
    ["L2", state.cyclical.posture_chip as PostureState],
    ["L3", state.valuation.posture_chip as PostureState],
  ];
  return (
    <Tile
      label="LENS POSTURE"
      value={
        <span
          style={{
            display: "flex",
            gap: 6,
            alignItems: "center",
            fontSize: 14,
          }}
        >
          {chips.map(([id, chip]) => (
            <span
              key={id}
              style={{ display: "inline-flex", gap: 4, alignItems: "center" }}
            >
              <span
                style={{
                  fontSize: 10,
                  letterSpacing: 1.5,
                  color: "var(--text-muted, #6b7280)",
                }}
              >
                {id}
              </span>
              <PostureChip state={chip} />
            </span>
          ))}
        </span>
      }
      sub="Structural · Cyclical · Valuation"
    />
  );
}
