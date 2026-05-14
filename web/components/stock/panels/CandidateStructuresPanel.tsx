import type { TradeInsightsResponse } from "@/lib/api";
import { InsightPanel, InsightStatusBanner } from "./InsightPanel";

type Candidate = TradeInsightsResponse["candidate_structures"][number];

const fmtMoney = (v: string | number | null | undefined) =>
  v == null ? "-" : `$${Number(v).toFixed(2)}`;
const readable = (value: string | null | undefined) =>
  (value ?? "unknown").replaceAll("_", " ");

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
          display: "flex",
          flexDirection: "column",
          gap: 12,
        }}
      >
        {candidates.map((candidate) => (
          <section
            key={candidate.idea_id}
            style={{
              border: "1px solid var(--border-dim)",
              borderRadius: 4,
              background: "var(--bg-base)",
              padding: 14,
              display: "grid",
              gap: 12,
            }}
          >
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "minmax(0, 1fr) auto",
                gap: 12,
                alignItems: "start",
              }}
            >
              <div>
                <div style={{ color: "var(--text-primary)", fontSize: 14, fontWeight: 700 }}>
                  {candidate.idea_id}. {readable(candidate.structure)}
                </div>
                <div style={{ color: "var(--text-secondary)", fontSize: 12, lineHeight: 1.5 }}>
                  {candidate.thesis}
                </div>
              </div>
              <div
                style={{
                  border: "1px solid var(--border-dim)",
                  color: "var(--text-secondary)",
                  fontFamily: "var(--font-mono)",
                  fontSize: 10,
                  padding: "4px 7px",
                  textTransform: "uppercase",
                  whiteSpace: "nowrap",
                }}
              >
                {readable(candidate.status)}
              </div>
            </div>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 150px), 1fr))",
                gap: "12px 18px",
              }}
            >
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
            {candidate.risk_flags.length > 0 && (
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "auto minmax(0, 1fr)",
                  gap: 8,
                  alignItems: "start",
                  color: "var(--warning)",
                  fontFamily: "var(--font-mono)",
                  fontSize: 11,
                  lineHeight: 1.4,
                }}
              >
                <span aria-hidden="true">!</span>
                <span>{candidate.risk_flags.map(readable).join("; ")}</span>
              </div>
            )}
          </section>
        ))}
      </div>
    </InsightPanel>
  );
}
