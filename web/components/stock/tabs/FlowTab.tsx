"use client";
import { useMemo, useState } from "react";
import type { components } from "@/lib/types";
import { FlowSnapshotGrid } from "../panels/FlowSnapshotGrid";
import { FlowTimelinePanel } from "../panels/FlowTimelinePanel";
import { OiMoversTable } from "../panels/OiMoversTable";
import { StrikeProfilePanel } from "../panels/StrikeProfilePanel";
import { TopAlertsTable } from "../panels/TopAlertsTable";
import { toNum } from "@/lib/formatters";

type Report = components["schemas"]["SingleStockReport"];
type OptionsDailyRow = components["schemas"]["OptionsDailyRow"];
type ChainRow = components["schemas"]["OptionChainPerStrikeRow"];

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
  const chain = useMemo<ChainRow[]>(
    () => report.option_chain_per_strike ?? [],
    [report.option_chain_per_strike],
  );

  // Cross-reference indexes for the two tables. Alerts key by `option_chain`
  // (OCC), OI movers key by `option_symbol` (OCC) — same alphabet.
  const alerts = report.flow.top_alerts ?? [];
  const oiMovers = report.oi_change_top ?? [];
  const alertCountBySymbol = useMemo(() => {
    const m = new Map<string, number>();
    for (const a of alerts) {
      if (!a.option_chain) continue;
      m.set(a.option_chain, (m.get(a.option_chain) ?? 0) + 1);
    }
    return m;
  }, [alerts]);
  const oiDiffBySymbol = useMemo(() => {
    const m = new Map<string, number>();
    for (const r of oiMovers) {
      if (!r.option_symbol || r.oi_diff_plain == null) continue;
      m.set(r.option_symbol, r.oi_diff_plain);
    }
    return m;
  }, [oiMovers]);

  // Stored chain rows are already filtered to dte ≥ 0 in
  // aggregate_chain_per_strike, so every expiry here is today-or-future.
  // Computing "today" in the client was the source of an SSR/CSR hydration
  // mismatch (Date()-based render-time state) — drop it.
  const expiries = useMemo(
    () => Array.from(new Set(chain.map((r) => r.expiry))).sort(),
    [chain],
  );
  const [selectedExpiries, setSelectedExpiries] = useState<string[]>(() =>
    expiries.slice(0, 4),
  );
  const [strikeRangePct, setStrikeRangePct] = useState<number>(0.3);

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

      {chain.length > 0 ? (
        <section style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <ProfileControls
            expiries={expiries}
            selectedExpiries={selectedExpiries}
            onToggleExpiry={(e) =>
              setSelectedExpiries((prev) =>
                prev.includes(e) ? prev.filter((x) => x !== e) : [...prev, e],
              )
            }
            strikeRangePct={strikeRangePct}
            onStrikeRangeChange={setStrikeRangePct}
          />
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 1fr",
              gap: 16,
            }}
          >
            <StrikeProfilePanel
              title="VOLUME BY STRIKE"
              metric="volume"
              rows={chain}
              selectedExpiries={selectedExpiries}
              strikeRangePct={strikeRangePct}
              spot={spot}
            />
            <StrikeProfilePanel
              title="OI BY STRIKE"
              metric="oi"
              rows={chain}
              selectedExpiries={selectedExpiries}
              strikeRangePct={strikeRangePct}
              spot={spot}
            />
          </div>
        </section>
      ) : (
        <div
          style={{
            fontFamily: "var(--font-mono)",
            color: "var(--text-muted)",
          }}
        >
          NO CHAIN DATA
        </div>
      )}

      <section>
        <h3 style={SECTION_HEADING}>Top Alerts</h3>
        <TopAlertsTable alerts={alerts} oiMoverIndex={oiDiffBySymbol} />
      </section>

      <section>
        <h3 style={SECTION_HEADING}>OI Change — Top Movers</h3>
        <OiMoversTable
          rows={oiMovers}
          spot={spot}
          alertIndex={alertCountBySymbol}
        />
      </section>
    </div>
  );
}

function ProfileControls({
  expiries,
  selectedExpiries,
  onToggleExpiry,
  strikeRangePct,
  onStrikeRangeChange,
}: {
  expiries: string[];
  selectedExpiries: string[];
  onToggleExpiry: (expiry: string) => void;
  strikeRangePct: number;
  onStrikeRangeChange: (v: number) => void;
}) {
  return (
    <div
      style={{
        display: "flex",
        gap: 12,
        flexWrap: "wrap",
        alignItems: "center",
      }}
    >
      <span
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 10,
          letterSpacing: 1.5,
          color: "var(--text-muted)",
        }}
      >
        EXPIRIES:
      </span>
      {expiries.map((e) => {
        const active = selectedExpiries.includes(e);
        return (
          <button
            key={e}
            onClick={() => onToggleExpiry(e)}
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 11,
              padding: "2px 8px",
              border: active
                ? "1px solid var(--accent-bg)"
                : "1px solid var(--border-dim)",
              background: active ? "var(--accent-bg)" : "transparent",
              color: active ? "var(--bg-panel)" : "var(--text-primary)",
              cursor: "pointer",
            }}
          >
            {e}
          </button>
        );
      })}
      <span
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 10,
          letterSpacing: 1.5,
          color: "var(--text-muted)",
          marginLeft: 16,
        }}
      >
        STRIKE RANGE:
      </span>
      <select
        value={strikeRangePct}
        onChange={(e) => onStrikeRangeChange(Number(e.target.value))}
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 11,
          background: "var(--bg-panel)",
          color: "var(--text-primary)",
          border: "1px solid var(--border-dim)",
          padding: "2px 8px",
        }}
      >
        <option value={0.15}>±15%</option>
        <option value={0.3}>±30%</option>
        <option value={0.6}>±60%</option>
        <option value={9.99}>All</option>
      </select>
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
