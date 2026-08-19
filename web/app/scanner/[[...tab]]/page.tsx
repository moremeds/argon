import DiscoverSubTab from "@/components/scanner/DiscoverSubTab";
import FlowSubTab from "@/components/scanner/FlowSubTab";
import ValueSubTab from "@/components/scanner/value/ValueSubTab";
import ScannerPanel from "@/components/scanner/ScannerPanel";
import { api } from "@/lib/api";

export const dynamic = "force-dynamic";

export const metadata = {
  title: "Scanner — Unusual Whales",
  description:
    "Flow scanner, own-history valuation buy zones, and Theta Harvester candidates",
};

const VALID_TABS = new Set(["flow", "discover", "value", "theta"]);

export default async function ScannerPage({
  params,
  searchParams,
}: {
  params: Promise<{ tab?: string[] }>;
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const { tab } = await params;
  const query = await searchParams;
  const first = tab?.[0];
  const initialTab = first && VALID_TABS.has(first) ? first : "flow";

  const qs = new URLSearchParams();
  if (query.type_f_only === "true") qs.set("type_f_only", "true");
  if (query.tier_1_only === "true") qs.set("tier_1_only", "true");
  if (typeof query.sector === "string") qs.set("sector", query.sector);

  // The route owns every fetch. Tab switching is pushState (no RSC round-trip),
  // so all slots are rendered up front regardless of which tab is active —
  // fetching inside each sub-tab would run the same requests AND still leave
  // the route unable to label the badges.
  const [data, queue, discover, value, theta] = await Promise.all([
    api.scanner(qs),
    api.queueSummary().catch(() => undefined),
    api.scannerDiscover(20).catch(() => undefined),
    // 503 (no active method version) lands here as undefined, which the
    // sub-tab renders as an outage rather than as an empty buy-zone list.
    api.scannerValue().catch(() => undefined),
    api.thetaHarvester().catch(() => undefined),
  ]);

  return (
    <div style={{ padding: 24, maxWidth: 1600, margin: "0 auto" }}>
      <header style={{ marginBottom: 16 }}>
        <h1
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 24,
            letterSpacing: 1,
          }}
        >
          SCANNER
        </h1>
      </header>
      <ScannerPanel
        initialTab={initialTab}
        counts={{
          flow: data.candidates.length,
          discover: discover?.candidates.length,
          value: value?.candidates.length,
          theta: theta?.candidates.length,
        }}
        theta={theta}
        flowContent={<FlowSubTab data={data} queue={queue} />}
        discoverContent={<DiscoverSubTab discover={discover} />}
        valueContent={<ValueSubTab value={value} />}
      />
    </div>
  );
}
