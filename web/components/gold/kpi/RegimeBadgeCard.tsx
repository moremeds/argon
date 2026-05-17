import type { components } from "@/lib/types";

import { Tile } from "../Tile";

type Gauge = components["schemas"]["GoldGaugeState"];

const stateToLabel: Record<string, string> = {
  operative: "OPERATIVE",
  partial: "PARTIAL",
  suspended: "SUSPENDED",
};

export function RegimeBadgeCard({ gauge }: { gauge: Gauge }) {
  const label = stateToLabel[gauge.state] ?? gauge.state.toUpperCase();
  const tone =
    gauge.state === "operative"
      ? "positive"
      : gauge.state === "suspended"
        ? "warning"
        : "default";
  return (
    <Tile
      label="GAUGE REGIME"
      tone={tone}
      value={label}
      sub={
        gauge.state === "suspended"
          ? "Cyclical view informative-only"
          : "Real-rate channel transmitting"
      }
    />
  );
}
