"use client";

import { useState } from "react";
import { useMarketHours } from "@/lib/regime/useMarketHours";
import CriSubTab from "./CriSubTab";
import GexSubTab from "./GexSubTab";
import PendingSubTab from "./PendingSubTab";

type RegimeTab = "cri" | "vcg" | "gex";

const TABS: { id: RegimeTab; label: string }[] = [
  { id: "gex", label: "GEX" },
  { id: "cri", label: "CRI" },
  { id: "vcg", label: "VCG" },
];

const VCG_DESC =
  "Volatility-Credit Gap — rolling OLS residual between the vol complex (VIX/VVIX) and cash credit (HYG/JNK/LQD). Renders when VIX/VVIX data is wired.";

export default function RegimePanel() {
  const [activeTab, setActiveTab] = useState<RegimeTab>("gex");
  const marketState = useMarketHours();

  return (
    <div className="regime-panel" data-testid="regime-panel">
      <div
        className="ticker-tabs"
        style={{ marginBottom: "16px" }}
        data-testid="regime-tabs"
      >
        {TABS.map((tab) => (
          <button
            key={tab.id}
            className={`ticker-tab ${activeTab === tab.id ? "active" : ""}`}
            onClick={() => setActiveTab(tab.id)}
            data-testid={`regime-tab-${tab.id}`}
          >
            {tab.label}
          </button>
        ))}
      </div>
      {activeTab === "gex" && <GexSubTab marketState={marketState} />}
      {activeTab === "cri" && <CriSubTab />}
      {activeTab === "vcg" && (
        <PendingSubTab name="VCG" description={VCG_DESC} />
      )}
    </div>
  );
}
