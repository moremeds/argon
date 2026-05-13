import type { components } from "@/lib/types";
import { api } from "@/lib/api";
import { GexLevelTiles } from "../panels/GexLevelTiles";
import { ExpectedRangeBar } from "../panels/ExpectedRangeBar";
import { DirectionalBiasPanel } from "../panels/DirectionalBiasPanel";
import { MarketStructureHistoryTable } from "../panels/MarketStructureHistoryTable";
import { GexProfileChart } from "../panels/GexProfileChart";
import { MaxPainTable } from "../panels/MaxPainTable";

type Report = components["schemas"]["SingleStockReport"];

export async function MarketStructureTab({ report }: { report: Report }) {
  let historyRows: components["schemas"]["StockHistoryRow"][] = [];
  try {
    const h = await api.stockHistory(report.ticker);
    historyRows = h.rows;
  } catch {
    historyRows = [];
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <GexLevelTiles report={report} />
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 12,
        }}
      >
        <ExpectedRangeBar report={report} />
        <DirectionalBiasPanel report={report} history={historyRows} />
      </div>
      <GexProfileChart report={report} />
      <MarketStructureHistoryTable rows={historyRows} />
      <MaxPainTable rows={report.max_pain_rows} />
    </div>
  );
}
