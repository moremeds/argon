"use client";

import { useEffect, useState } from "react";
import ThetaSubTab from "./theta/ThetaSubTab";

type ScannerTab = "flow" | "theta";

const TABS: { id: ScannerTab; label: string }[] = [
  { id: "flow", label: "Flow" },
  { id: "theta", label: "Theta Harvester" },
];

const VALID = new Set<ScannerTab>(TABS.map((t) => t.id));

function coerce(tab: string | undefined): ScannerTab {
  return tab && VALID.has(tab as ScannerTab) ? (tab as ScannerTab) : "flow";
}

export default function ScannerPanel({
  initialTab,
  flowContent,
}: {
  initialTab?: string;
  flowContent?: React.ReactNode;
}) {
  // Mirrors RegimePanel: local state renders instantly, the URL is kept in sync
  // via pushState + a popstate listener so deep-links and back/forward both work
  // without an RSC round-trip per tab click.
  const [activeTab, setActiveTab] = useState<ScannerTab>(coerce(initialTab));
  const [seenInitial, setSeenInitial] = useState(initialTab);
  if (initialTab !== seenInitial) {
    setSeenInitial(initialTab);
    setActiveTab(coerce(initialTab));
  }

  useEffect(() => {
    function onPop() {
      setActiveTab(coerce(window.location.pathname.split("/")[2]));
    }
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  function selectTab(id: ScannerTab) {
    setActiveTab(id);
    if (typeof window !== "undefined") {
      window.history.pushState(null, "", `/scanner/${id}`);
    }
  }

  return (
    <div data-testid="scanner-panel">
      <div
        className="ticker-tabs"
        style={{ marginBottom: 16, flexWrap: "wrap" }}
        data-testid="scanner-tabs"
      >
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            className={activeTab === t.id ? "active" : ""}
            onClick={() => selectTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>
      {/* flowContent arrives as an already-rendered server slot — FlowSubTab is
          an async server component and cannot be imported into a client one. */}
      {activeTab === "flow" ? flowContent : <ThetaSubTab />}
    </div>
  );
}
