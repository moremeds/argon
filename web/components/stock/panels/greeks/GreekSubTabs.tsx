"use client";

import { useState } from "react";
import type { components } from "@/lib/types";
import { GexHistoryChart } from "@/components/stock/panels/GexHistoryChart";
import { GexProfileChart } from "@/components/stock/panels/GexProfileChart";
import { MagnetGammaBar } from "@/components/stock/panels/MagnetGammaBar";
import { CharmPanel } from "./CharmPanel";
import { VannaPanel } from "./VannaPanel";

type Report = components["schemas"]["SingleStockReport"];
type Tab = "GEX" | "VANNA" | "CHARM";
const TABS: Tab[] = ["GEX", "VANNA", "CHARM"];

const ACTIVE_TAB: React.CSSProperties = {
  background: "var(--bg-panel)",
  color: "var(--text-primary)",
  borderBottom: "2px solid var(--accent-vol)",
};
const TAB_BASE: React.CSSProperties = {
  background: "transparent",
  border: "none",
  borderBottom: "2px solid transparent",
  padding: "8px 16px",
  fontFamily: "var(--font-mono)",
  fontSize: 12,
  letterSpacing: 1.5,
  textTransform: "uppercase",
  color: "var(--text-muted)",
  cursor: "pointer",
};

export function GreekSubTabs({ report }: { report: Report }) {
  const [tab, setTab] = useState<Tab>("GEX");

  return (
    <div
      style={{
        background: "var(--bg-panel)",
        border: "1px solid var(--border-dim)",
        borderRadius: 4,
        padding: 16,
      }}
    >
      <div
        role="tablist"
        style={{
          display: "flex",
          gap: 4,
          borderBottom: "1px solid var(--border-dim)",
          marginBottom: 16,
        }}
      >
        {TABS.map((t) => (
          <button
            key={t}
            role="tab"
            aria-selected={tab === t}
            onClick={() => setTab(t)}
            style={tab === t ? { ...TAB_BASE, ...ACTIVE_TAB } : TAB_BASE}
          >
            {t}
          </button>
        ))}
      </div>

      {tab === "GEX" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <MagnetGammaBar report={report} />
          <GexProfileChart report={report} />
          <GexHistoryChart ticker={report.ticker} />
        </div>
      )}
      {tab === "VANNA" && (
        <VannaPanel
          ticker={report.ticker}
          strikeExposures={report.strike_exposures ?? []}
          summary={report.exposures_summary ?? []}
        />
      )}
      {tab === "CHARM" && (
        <CharmPanel
          ticker={report.ticker}
          strikeExposures={report.strike_exposures ?? []}
          summary={report.exposures_summary ?? []}
        />
      )}
    </div>
  );
}
