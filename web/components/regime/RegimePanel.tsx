"use client";

import { useEffect, useState } from "react";
import { useMarketHours } from "@/lib/regime/useMarketHours";
import CanarySubTab from "./CanarySubTab";
import CriSubTab from "./CriSubTab";
import GexSubTab from "./GexSubTab";
import GrgSubTab from "./GrgSubTab";
import ValidationTab from "./ValidationTab";
import VcgSubTab from "./VcgSubTab";

type RegimeTab = "cri" | "vcg" | "grg" | "canary" | "gex" | "validation";

const TABS: { id: RegimeTab; label: string }[] = [
  { id: "gex", label: "GEX" },
  { id: "cri", label: "CRI" },
  { id: "vcg", label: "VCG" },
  { id: "grg", label: "GRG" },
  { id: "canary", label: "5% CANARY" },
  { id: "validation", label: "VALIDATION" },
];

const VALID = new Set<RegimeTab>(TABS.map((t) => t.id));

function coerce(tab: string | undefined): RegimeTab {
  return tab && VALID.has(tab as RegimeTab) ? (tab as RegimeTab) : "gex";
}

export default function RegimePanel({ initialTab }: { initialTab?: string }) {
  // Local state is the source of truth for rendering — instant tab switches,
  // no RSC round-trip, unit-testable without a router context. The URL is kept
  // in sync three ways so deep-links + history all work:
  //   • `initialTab` (server/param-derived) seeds state AND re-syncs on change,
  //     which covers <Link>/router.push navigations to a new /regime/<tab>
  //     (the page RSC re-renders with a new initialTab).
  //   • pushState on click updates the address bar without a navigation.
  //   • a popstate listener handles browser back/forward.
  const [activeTab, setActiveTab] = useState<RegimeTab>(coerce(initialTab));
  // React's "adjust state when a prop changes" pattern — set during render,
  // not in an effect (avoids react-hooks/set-state-in-effect). Re-syncs when
  // a <Link>/router.push navigation re-renders the page with a new initialTab.
  const [seenInitial, setSeenInitial] = useState(initialTab);
  if (initialTab !== seenInitial) {
    setSeenInitial(initialTab);
    setActiveTab(coerce(initialTab));
  }
  const marketState = useMarketHours();

  useEffect(() => {
    function onPop() {
      const seg = window.location.pathname.split("/")[2];
      setActiveTab(coerce(seg));
    }
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  function selectTab(id: RegimeTab) {
    setActiveTab(id);
    if (typeof window !== "undefined") {
      window.history.pushState(null, "", `/regime/${id}`);
    }
  }

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
            onClick={() => selectTab(tab.id)}
            data-testid={`regime-tab-${tab.id}`}
          >
            {tab.label}
          </button>
        ))}
      </div>
      {activeTab === "gex" && <GexSubTab marketState={marketState} />}
      {activeTab === "cri" && <CriSubTab />}
      {activeTab === "vcg" && <VcgSubTab />}
      {activeTab === "grg" && <GrgSubTab />}
      {activeTab === "canary" && <CanarySubTab />}
      {activeTab === "validation" && <ValidationTab />}
    </div>
  );
}
