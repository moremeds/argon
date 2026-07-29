import FlowSubTab from "@/components/scanner/FlowSubTab";
import ScannerPanel from "@/components/scanner/ScannerPanel";

export const dynamic = "force-dynamic";

export const metadata = {
  title: "Scanner — Unusual Whales",
  description: "Flow scanner and Theta Harvester short-strangle candidates",
};

const VALID_TABS = new Set(["flow", "theta"]);

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
        flowContent={<FlowSubTab params={query} />}
      />
    </div>
  );
}
