"use client";

import { useState } from "react";
import { useMarketHours } from "@/lib/regime/useMarketHours";
import CanarySubTab from "./CanarySubTab";
import CriSubTab from "./CriSubTab";
import GexSubTab from "./GexSubTab";
import ValidationTab from "./ValidationTab";
import VcgSubTab from "./VcgSubTab";

type RegimeTab = "cri" | "vcg" | "canary" | "gex" | "validation";

const TABS: { id: RegimeTab; label: string }[] = [
  { id: "gex", label: "GEX" },
  { id: "cri", label: "CRI" },
  { id: "vcg", label: "VCG" },
  { id: "canary", label: "5% CANARY" },
  { id: "validation", label: "VALIDATION" },
];

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
      {activeTab === "vcg" && <VcgSubTab />}
      {activeTab === "canary" && <CanarySubTab />}
      {activeTab === "validation" && <ValidationTab />}
    </div>
  );
}
