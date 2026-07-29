"use client";

import { useEffect, useState } from "react";
import ThetaSubTab from "./theta/ThetaSubTab";

type ScannerTab = "flow" | "discover" | "theta";

const TABS: { id: ScannerTab; label: string }[] = [
  { id: "flow", label: "Flow Signals" },
  { id: "discover", label: "Discover" },
  { id: "theta", label: "Theta Harvester" },
];

const VALID = new Set<ScannerTab>(TABS.map((t) => t.id));

function coerce(tab: string | undefined): ScannerTab {
  return tab && VALID.has(tab as ScannerTab) ? (tab as ScannerTab) : "flow";
}

export default function ScannerPanel({
  initialTab,
  counts,
  theta,
  flowContent,
  discoverContent,
}: {
  initialTab?: string;
  // Counts come from the server so every badge is correct on first paint,
  // including for tabs that have not been opened yet.
  counts?: Partial<Record<ScannerTab, number>>;
  theta?: React.ComponentProps<typeof ThetaSubTab>["initial"];
  flowContent?: React.ReactNode;
  discoverContent?: React.ReactNode;
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
      <div className="scanner-tabs" data-testid="scanner-tabs">
        {TABS.map((t) => {
          const count = counts?.[t.id];
          return (
            <button
              key={t.id}
              type="button"
              className={`scanner-tab ${activeTab === t.id ? "active" : ""}`}
              onClick={() => selectTab(t.id)}
            >
              {t.label}
              {count != null ? (
                <span className="scanner-tab-badge">{count}</span>
              ) : null}
            </button>
          );
        })}
      </div>
      <div style={{ paddingTop: 16 }}>
        {/* Flow and Discover arrive as already-rendered server slots — they are
            async server components and cannot be imported into a client one. */}
        {activeTab === "flow" ? flowContent : null}
        {activeTab === "discover" ? discoverContent : null}
        {activeTab === "theta" ? <ThetaSubTab initial={theta} /> : null}
      </div>
    </div>
  );
}
