"use client";

import { useState } from "react";
import type {
  CockpitDealerResponse,
  CockpitFlowImResponse,
  CockpitStateResponse,
  CockpitSurfaceResponse,
  CockpitVrpResponse,
} from "@/lib/api";
import { CockpitDealerTab } from "./CockpitDealerTab";
import { CockpitFlowImTab } from "./CockpitFlowImTab";
import { CockpitSurfaceTab } from "./CockpitSurfaceTab";
import { CockpitVrpTab } from "./CockpitVrpTab";
import { StateTab } from "./StateTab";

type TabId = "state" | "dealer" | "surface" | "flow-im" | "vrp";

const TABS: { id: TabId; label: string }[] = [
  { id: "state", label: "State" },
  { id: "dealer", label: "Dealer" },
  { id: "surface", label: "Surface" },
  { id: "flow-im", label: "Flow + IM" },
  { id: "vrp", label: "VRP" },
];

export function CockpitTabs({
  ticker,
  stateData,
  dealerData,
  surfaceData,
  flowImData,
  vrpData,
}: {
  ticker: string;
  stateData: CockpitStateResponse | null;
  dealerData: CockpitDealerResponse | null;
  surfaceData: CockpitSurfaceResponse | null;
  flowImData: CockpitFlowImResponse | null;
  vrpData: CockpitVrpResponse | null;
}) {
  const [active, setActive] = useState<TabId>("state");

  return (
    <div style={{ display: "grid", gap: 14 }}>
      <div
        role="tablist"
        aria-label={`${ticker} cockpit tabs`}
        style={{
          display: "flex",
          gap: 8,
          overflowX: "auto",
          borderBottom: "1px solid var(--border-dim)",
          paddingBottom: 8,
        }}
      >
        {TABS.map((tab) => {
          const selected = active === tab.id;
          return (
            <button
              key={tab.id}
              type="button"
              role="tab"
              aria-selected={selected}
              onClick={() => setActive(tab.id)}
              style={{
                minHeight: 34,
                padding: "8px 12px",
                border: "1px solid var(--border-dim)",
                background: selected
                  ? "var(--bg-panel-raised)"
                  : "var(--bg-panel)",
                color: selected
                  ? "var(--accent-bg)"
                  : "var(--text-secondary)",
                cursor: "pointer",
                fontFamily: "var(--font-mono)",
                fontSize: 12,
                fontWeight: selected ? 800 : 600,
                letterSpacing: 0,
                whiteSpace: "nowrap",
              }}
            >
              {tab.label}
            </button>
          );
        })}
      </div>

      {active === "state" ? <StateTab ticker={ticker} data={stateData} /> : null}
      {active === "dealer" ? (
        <CockpitDealerTab ticker={ticker} data={dealerData} />
      ) : null}
      {active === "surface" ? (
        <CockpitSurfaceTab
          ticker={ticker}
          data={surfaceData}
          stateData={stateData}
        />
      ) : null}
      {active === "flow-im" ? (
        <CockpitFlowImTab ticker={ticker} data={flowImData} />
      ) : null}
      {active === "vrp" ? (
        <CockpitVrpTab ticker={ticker} data={vrpData} stateData={stateData} />
      ) : null}
    </div>
  );
}
