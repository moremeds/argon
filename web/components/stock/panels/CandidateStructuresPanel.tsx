import type { TradeInsightsResponse } from "@/lib/api";
import { InsightPanel, InsightStatusBanner } from "./InsightPanel";

type Candidate = TradeInsightsResponse["candidate_structures"][number];

const fmtMoney = (v: string | number | null | undefined) =>
  v == null ? "-" : `$${Number(v).toFixed(2)}`;

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div
        style={{
          color: "var(--text-muted)",
          fontFamily: "var(--font-mono)",
          fontSize: 10,
          textTransform: "uppercase",
        }}
      >
        {label}
      </div>
      <div style={{ color: "var(--text-primary)", fontFamily: "var(--font-mono)" }}>
        {value}
      </div>
    </div>
  );
}

export function CandidateStructuresPanel({
  candidates,
}: {
  candidates: Candidate[];
}) {
  if (candidates.length === 0) {
    return (
      <InsightPanel heading="CANDIDATE STRUCTURES">
        <InsightStatusBanner text="No candidate structures generated" severity="info" />
      </InsightPanel>
    );
  }

  return (
    <InsightPanel heading="CANDIDATE STRUCTURES">
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))",
          gap: 8,
        }}
      >
        {candidates.map((candidate) => (
          <section
            key={candidate.idea_id}
            style={{
              border: "1px solid var(--border-dim)",
              borderRadius: 4,
              padding: 12,
              display: "grid",
              gap: 8,
            }}
          >
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                gap: 8,
                fontFamily: "var(--font-mono)",
              }}
            >
              <div style={{ color: "var(--text-primary)", fontSize: 13 }}>
                {candidate.idea_id}. {candidate.structure}
              </div>
              <div style={{ color: "var(--text-secondary)", fontSize: 11 }}>
                {candidate.status}
              </div>
            </div>
            <div style={{ color: "var(--text-secondary)", fontSize: 12 }}>
              {candidate.thesis}
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
              <Metric label="Credit / Debit" value={fmtMoney(candidate.net_credit_debit)} />
              <Metric label="Max profit" value={fmtMoney(candidate.max_profit)} />
              <Metric label="Max loss" value={fmtMoney(candidate.max_loss)} />
              <Metric label="Rank" value={String(candidate.rank)} />
            </div>
            {candidate.profit_zone && (
              <div
                style={{
                  color: "var(--text-secondary)",
                  fontFamily: "var(--font-mono)",
                  fontSize: 11,
                }}
              >
                {candidate.profit_zone}
              </div>
            )}
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              {candidate.risk_flags.map((flag) => (
                <span
                  key={flag}
                  style={{
                    border: "1px solid var(--border-dim)",
                    color: "var(--warning)",
                    padding: "3px 6px",
                    fontFamily: "var(--font-mono)",
                    fontSize: 10,
                  }}
                >
                  {flag}
                </span>
              ))}
            </div>
          </section>
        ))}
      </div>
    </InsightPanel>
  );
}
