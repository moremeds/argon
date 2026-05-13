import type { components } from "@/lib/types";
import { FlowSnapshotGrid } from "../panels/FlowSnapshotGrid";
import { OiMoversTable } from "../panels/OiMoversTable";
import { TopAlertsTable } from "../panels/TopAlertsTable";
import { toNum } from "@/lib/formatters";

type Report = components["schemas"]["SingleStockReport"];

const SECTION_HEADING: React.CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: 12,
  letterSpacing: 1.5,
  textTransform: "uppercase",
  color: "var(--text-muted)",
  margin: "8px 0",
};

export function FlowTab({ report }: { report: Report }) {
  // Derive spot from the report itself — keeps FlowTab's signature single-prop
  // (matches MarketStructureTab/VolatilityTab) so the dispatcher needs no
  // changes when wiring this tab.
  const spot = toNum(report.market_structure?.spot) ?? 0;

  return (
    <div
      style={{ display: "flex", flexDirection: "column", gap: 24, padding: 16 }}
    >
      <FlowSnapshotGrid
        flow={report.flow}
        darkPool={{
          prints: report.dark_pool_print_count,
          notional: report.dark_pool_notional,
        }}
        shortData={report.short_data ?? null}
      />

      <section>
        <h3 style={SECTION_HEADING}>Top Alerts</h3>
        <TopAlertsTable alerts={report.flow.top_alerts ?? []} />
      </section>

      <section>
        <h3 style={SECTION_HEADING}>OI Change — Top Movers</h3>
        <OiMoversTable rows={report.oi_change_top ?? []} spot={spot} />
      </section>
    </div>
  );
}
