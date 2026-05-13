import { api } from "@/lib/api";
import type { components } from "@/lib/types";

import { VolatilityTabClient } from "./VolatilityTabClient";

type Report = components["schemas"]["SingleStockReport"];

export async function VolatilityTab({ report }: { report: Report }) {
  const initial = await api.volatilitySeries(report.ticker);
  return <VolatilityTabClient ticker={report.ticker} initial={initial} />;
}
