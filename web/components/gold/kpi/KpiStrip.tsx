import type { components } from "@/lib/types";

import { CorrelationGaugeCard } from "./CorrelationGaugeCard";
import { DataFreshnessCard } from "./DataFreshnessCard";
import { LensesOverallCard } from "./LensesOverallCard";
import { RegimeBadgeCard } from "./RegimeBadgeCard";
import { SpotPriceCard } from "./SpotPriceCard";

type State = components["schemas"]["GoldStateResponse"];

export function KpiStrip({ state }: { state: State }) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(5, minmax(0, 1fr))",
        gap: 12,
      }}
    >
      <SpotPriceCard spot={state.spot} />
      <CorrelationGaugeCard gauge={state.gauge} />
      <RegimeBadgeCard gauge={state.gauge} />
      <LensesOverallCard state={state} />
      <DataFreshnessCard sources={state.data_freshness} />
    </div>
  );
}
