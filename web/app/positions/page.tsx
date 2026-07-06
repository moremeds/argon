import { PositionsPanel } from "@/components/positions/PositionsPanel";
import { api } from "@/lib/api";
import { fmtSigned, toNum } from "@/lib/formatters";

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

export default async function PositionsPage() {
  const data = await api.positions().catch(() => null);
  const positions = data?.positions ?? [];
  const total = toNum(data?.total_unrealized_pnl ?? null);
  const disclaimer =
    data?.disclaimer ??
    "Modeled P&L from persisted NBBO mids. Paper/backtest only — not executed.";

  return (
    <main style={{ padding: 24, maxWidth: 1200, margin: "0 auto" }}>
      <h1 style={{ fontSize: 20, marginBottom: 4 }}>Trade Lifecycle</h1>
      <p style={{ color: "var(--text-muted)", fontSize: 13, marginBottom: 16 }}>
        VRP-macro entry-capture cohorts read back as a portfolio — entry credit,
        latest mark, running P&L, and expiry status. Click a row for its P&L
        curve.
      </p>
      <div
        style={{
          background: "var(--bg-elevated, #1a1a1a)",
          border: "1px solid var(--warning)",
          borderRadius: 6,
          padding: "10px 14px",
          margin: "0 0 20px",
          color: "var(--warning)",
          fontSize: 12,
          fontFamily: "var(--font-mono)",
        }}
      >
        ⚠ {disclaimer}
      </div>

      <section style={PANEL}>
        <div style={H2}>
          Open Positions ({data?.open_count ?? 0}) · Unrealized{" "}
          <span
            style={{
              color:
                total == null
                  ? "var(--text-muted)"
                  : total > 0
                    ? "var(--positive)"
                    : total < 0
                      ? "var(--negative)"
                      : "var(--text-muted)",
            }}
          >
            {total == null ? "—" : fmtSigned(total, 2)} pts
          </span>
        </div>
        <PositionsPanel positions={positions} />
      </section>
    </main>
  );
}
