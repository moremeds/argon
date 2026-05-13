import type { components } from "@/lib/types";
import { FlowSnapshotGrid } from "../panels/FlowSnapshotGrid";
import { FlowTimelinePanel } from "../panels/FlowTimelinePanel";
import { OiMoversTable } from "../panels/OiMoversTable";
import { TopAlertsTable } from "../panels/TopAlertsTable";
import { toNum } from "@/lib/formatters";

type Report = components["schemas"]["SingleStockReport"];
type OptionsDailyRow = components["schemas"]["OptionsDailyRow"];

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

      <TimelineSection
        timeline={report.options_timeline ?? []}
        nextEarnings={report.next_earnings_date ?? null}
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

function TimelineSection({
  timeline,
  nextEarnings,
}: {
  timeline: OptionsDailyRow[];
  nextEarnings: string | null;
}) {
  if (timeline.length === 0) {
    return (
      <div
        style={{ fontFamily: "var(--font-mono)", color: "var(--text-muted)" }}
      >
        NO TIMELINE DATA
      </div>
    );
  }

  const dates = timeline.map((r) => r.date);
  const totalVol = timeline.map((r) =>
    r.call_volume == null || r.put_volume == null
      ? null
      : r.call_volume + r.put_volume,
  );
  // P/C ratio: only the DENOMINATOR (call_volume) must be non-zero. A real
  // put_volume of 0 should chart as 0, not get filtered out as missing.
  const pcVol = timeline.map((r) =>
    r.call_volume != null && r.call_volume !== 0 && r.put_volume != null
      ? r.put_volume / r.call_volume
      : null,
  );
  const totalOi = timeline.map((r) =>
    r.call_open_interest == null || r.put_open_interest == null
      ? null
      : r.call_open_interest + r.put_open_interest,
  );
  const pcOi = timeline.map((r) =>
    r.call_open_interest != null &&
    r.call_open_interest !== 0 &&
    r.put_open_interest != null
      ? r.put_open_interest / r.call_open_interest
      : null,
  );
  const earnings = nextEarnings ? [nextEarnings] : [];

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
      <FlowTimelinePanel
        title="OPTIONS VOLUME"
        primary={{
          label: "Volume",
          values: totalVol,
          color: "var(--accent-bg)",
        }}
        secondary={{
          label: "P/C Vol",
          values: pcVol,
          color: "var(--accent-warm)",
        }}
        dates={dates}
        markers={earnings}
      />
      <FlowTimelinePanel
        title="OPEN INTEREST"
        primary={{ label: "OI", values: totalOi, color: "var(--accent-bg)" }}
        secondary={{
          label: "P/C OI",
          values: pcOi,
          color: "var(--accent-warm)",
        }}
        dates={dates}
      />
    </div>
  );
}
