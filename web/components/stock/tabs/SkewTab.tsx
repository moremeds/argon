import { api } from "@/lib/api";
import type { components } from "@/lib/types";

import { SkewTabClient } from "./SkewTabClient";

type Report = components["schemas"]["SingleStockReport"];

export async function SkewTab({ report }: { report: Report }) {
  const initial = await api.skewAnalysis(report.ticker);
  return <SkewTabClient ticker={report.ticker} initial={initial} />;
}
