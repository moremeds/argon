import { BacktestSummary } from "@/components/vrp/BacktestSummary";
import { CandidatesTable } from "@/components/vrp/CandidatesTable";
import { PaperLedger } from "@/components/vrp/PaperLedger";
import { api } from "@/lib/api";

export const dynamic = "force-dynamic";

const PANEL: React.CSSProperties = {
  background: "var(--bg-panel)",
  border: "1px solid var(--border)",
  borderRadius: 6,
  padding: 16,
  marginBottom: 20,
};

const H2: React.CSSProperties = {
  fontSize: 11,
  letterSpacing: 2,
  textTransform: "uppercase",
  color: "var(--text-muted)",
  fontFamily: "var(--font-mono)",
  marginBottom: 12,
};

export default async function VrpPage() {
  const [candidates, backtest, paper] = await Promise.all([
    api.vrpCandidates().catch(() => null),
    api.vrpBacktest().catch(() => null),
    api.vrpPaper().catch(() => null),
  ]);

  const disclaimer =
    candidates?.disclaimer ??
    backtest?.disclaimer ??
    paper?.disclaimer ??
    "Flat-vol modeled credit (skew ignored). Paper/backtest only — not executed.";

  return (
    <main style={{ padding: 24, maxWidth: 1200, margin: "0 auto" }}>
      <h1 style={{ fontSize: 20, marginBottom: 4 }}>VRP Iron-Condor Trading</h1>
      <div
        style={{
          background: "var(--bg-elevated, #1a1a1a)",
          border: "1px solid var(--warning)",
          borderRadius: 6,
          padding: "10px 14px",
          margin: "12px 0 20px",
          color: "var(--warning)",
          fontSize: 12,
          fontFamily: "var(--font-mono)",
        }}
      >
        ⚠ {disclaimer}
      </div>

      <section style={PANEL}>
        <div style={H2}>Today&apos;s Candidates</div>
        <CandidatesTable candidates={candidates?.candidates ?? []} />
      </section>

      <section style={PANEL}>
        <div style={H2}>
          Backtest — full vs holdout (holdout = honest headline)
        </div>
        <BacktestSummary results={backtest?.results ?? []} />
      </section>

      <section style={PANEL}>
        <div style={H2}>Paper Ledger</div>
        <PaperLedger
          positions={paper?.positions ?? []}
          totalRealizedPnl={paper?.total_realized_pnl ?? null}
        />
      </section>
    </main>
  );
}
