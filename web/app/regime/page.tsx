import RegimePanel from "@/components/regime/RegimePanel";
import VolBackdropStrip from "@/components/regime/VolBackdropStrip";

export const metadata = {
  title: "Regime — Unusual Whales",
  description: "Market-wide regime indicators: CRI, VCG, GEX",
};

export default function RegimePage() {
  return (
    <main className="regime-page">
      <header className="regime-page-header">
        <h1>Regime</h1>
        <p className="regime-page-subtitle">
          Crash Risk Indicator · Vol-Curve Gauge · Gamma Exposure
        </p>
      </header>
      <VolBackdropStrip />
      <RegimePanel />
    </main>
  );
}
