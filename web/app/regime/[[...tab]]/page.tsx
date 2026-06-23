import RegimePanel from "@/components/regime/RegimePanel";
import VolBackdropStrip from "@/components/regime/VolBackdropStrip";

export const metadata = {
  title: "Regime — Unusual Whales",
  description: "Market-wide regime indicators: GEX, CRI, VCG, GRG",
};

const VALID_TABS = new Set([
  "gex",
  "cri",
  "vcg",
  "grg",
  "canary",
  "macro-short-vol",
  "validation",
]);

export default async function RegimePage({
  params,
}: {
  params: Promise<{ tab?: string[] }>;
}) {
  const { tab } = await params;
  const first = tab?.[0];
  const initialTab = first && VALID_TABS.has(first) ? first : "gex";
  return (
    <main className="regime-page">
      <header className="regime-page-header">
        <h1>Regime</h1>
        <p className="regime-page-subtitle">
          Crash Risk Indicator · Vol-Curve Gauge · Gamma Exposure · Gamma
          Rotation Gap
        </p>
      </header>
      <VolBackdropStrip />
      <RegimePanel initialTab={initialTab} />
    </main>
  );
}
