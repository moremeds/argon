"use client";

import { Zap } from "lucide-react";

import InfoTooltip from "@/components/regime/InfoTooltip";
import type { SkewAnalysisResponse } from "@/lib/api";
import { fmtDecimal, fmtSigned, toNum } from "@/lib/formatters";

// RICH = expensive wing (caution/amber), CHEAP = on-sale (positive),
// NORMAL/other = neutral-informational (violet).
export function deviationColor(cls: string): string {
  if (cls === "RICH") return "var(--warning)";
  if (cls === "CHEAP") return "var(--positive)";
  return "var(--info)";
}

function leanColor(lean: string): string {
  if (lean === "BULLISH_TILT") return "var(--positive)";
  if (lean === "BEARISH_TILT") return "var(--negative)";
  return "var(--text-muted)";
}

function leanLabel(lean: string): string {
  if (lean === "BULLISH_TILT") return "BULLISH";
  if (lean === "BEARISH_TILT") return "BEARISH";
  return "NEUTRAL";
}

function rvLabel(cls: string): string {
  if (cls === "RICH") return "FADE / FINANCE";
  if (cls === "CHEAP") return "OWN OPTIONALITY";
  return "NO EDGE";
}

// A gated-lean basis is always "validated — <clause>; <clause>". Lift the
// leading "validated" status into a right-aligned badge on the confidence row,
// and break the reason at its semicolon into two readable lines. NEUTRAL bases
// are plain reason strings (some of which contain " — "), so the badge triggers
// only on the literal "validated — " prefix — those render as a single line.
function parseEvidenceBasis(basis: string): {
  status: string | null;
  lines: string[];
} {
  const prefix = "validated — ";
  if (!basis.startsWith(prefix)) return { status: null, lines: [basis] };
  const rest = basis.slice(prefix.length).trim();
  const semi = rest.indexOf("; ");
  const lines =
    semi >= 0 ? [rest.slice(0, semi + 1), rest.slice(semi + 2)] : [rest];
  return { status: "validated", lines };
}

const labelStyle: React.CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: "10px",
  textTransform: "uppercase",
  letterSpacing: "0.08em",
  color: "var(--text-muted)",
};
const valueStyle: React.CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: "11px",
  fontWeight: 700,
};
const descStyle: React.CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: "11px",
  color: "var(--text-secondary)",
  marginTop: "5px",
  lineHeight: 1.5,
};

function Row({
  label,
  desc,
  value,
  valueColor,
  valueSub,
  last,
}: {
  label: string;
  desc: string;
  value: string;
  valueColor: string;
  valueSub?: string;
  last?: boolean;
}) {
  return (
    <div
      style={{
        padding: "10px 0",
        borderBottom: last
          ? "none"
          : "1px solid var(--border-dim, var(--line-grid))",
      }}
    >
      {/* Top line: label (left) + sub · value (right, value flush-right) */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
          gap: "12px",
        }}
      >
        <span style={labelStyle}>{label}</span>
        <span
          style={{
            display: "flex",
            alignItems: "baseline",
            gap: "8px",
            flexShrink: 0,
          }}
        >
          {valueSub ? (
            <span
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: "10px",
                color: "var(--text-muted)",
              }}
            >
              {valueSub}
            </span>
          ) : null}
          <span style={{ ...valueStyle, color: valueColor }}>{value}</span>
        </span>
      </div>
      {/* Explanation gets the full card width — one readable line. */}
      <div style={descStyle}>{desc}</div>
    </div>
  );
}

function EvidenceRow({ label, value }: { label: string; value: string }) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        gap: "16px",
        fontFamily: "var(--font-mono)",
        fontSize: "11px",
        padding: "3px 0",
      }}
    >
      <span style={{ color: "var(--text-muted)", flexShrink: 0 }}>{label}</span>
      <span style={{ color: "var(--text-secondary)", textAlign: "right" }}>
        {value}
      </span>
    </div>
  );
}

function StructureDetail({
  detail,
}: {
  detail: NonNullable<
    SkewAnalysisResponse["read"]["directional_lean"]["structure_detail"]
  >;
}) {
  if (detail.status !== "ready" || !detail.legs?.length) return null;
  return (
    <div
      data-testid="skew-structure-detail"
      style={{
        borderTop: "1px solid var(--border-dim, var(--line-grid))",
        marginTop: "8px",
        paddingTop: "8px",
      }}
    >
      <div style={{ ...labelStyle, marginBottom: "6px" }}>
        Structure · {detail.kind.replace(/_/g, "-")}
        {detail.dte_target ? ` · ${detail.dte_target}DTE` : ""}
      </div>
      {detail.legs.map((leg, i) => (
        <div
          key={i}
          style={{
            display: "flex",
            justifyContent: "space-between",
            fontFamily: "var(--font-mono)",
            fontSize: "11px",
            padding: "2px 0",
          }}
        >
          <span style={{ color: "var(--text-muted)" }}>
            {leg.action} {leg.right}
          </span>
          <span style={{ color: "var(--text-secondary)" }}>
            {leg.strike != null ? String(leg.strike) : "—"}
            {leg.actual_delta != null
              ? ` (Δ ${fmtSigned(toNum(leg.actual_delta) ?? 0, 2)})`
              : ""}
          </span>
        </div>
      ))}
      {detail.note ? (
        <div
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: "10px",
            color: "var(--text-muted)",
            marginTop: "5px",
            lineHeight: 1.4,
          }}
        >
          {detail.note}
        </div>
      ) : null}
    </div>
  );
}

export function SkewSignalDetail({ data }: { data: SkewAnalysisResponse }) {
  const read = data.read;
  const lean = read.directional_lean;
  // Explanation prose comes from the backend-built bullets (single source of
  // truth, unit-tested); look up each body by its label prefix so we don't
  // depend on array order.
  const bodyByKey = new Map<string, string>();
  for (const b of read.summary_bullets ?? []) {
    bodyByKey.set((b.label ?? "").split(" — ")[0], b.body ?? "");
  }
  const z = toNum(data.rr_z_180d);
  const pct = toNum(data.rr_pct_252d);
  const evidence = parseEvidenceBasis(lean.basis ?? "");

  return (
    <div className="section" data-testid="skew-signal-detail">
      <div className="section-header">
        <div className="section-title">
          <Zap size={14} />
          Signal Detail
          <InfoTooltip text="First-principles skew read: deviation vs the ticker's own baseline, what's driving it, whether spot-vol corroborates, and the relative-value implication. The directional lean (top-right) is evidence-gated to the markout — NEUTRAL unless a validated bucket verdict and the borrow/earnings/regime gates all pass." />
        </div>
        <span
          className="pill"
          style={{
            background: `${leanColor(lean.lean)}22`,
            color: leanColor(lean.lean),
            border: `1px solid ${leanColor(lean.lean)}55`,
            fontSize: "9px",
          }}
          data-testid="skew-lean-pill"
        >
          {leanLabel(lean.lean)}
        </span>
      </div>

      <div
        className="metrics-grid"
        style={{ gridTemplateColumns: "1.5fr 1fr" }}
      >
        {/* Left: the read, row by row */}
        <div className="metric-card" style={{ padding: "12px 16px" }}>
          <Row
            label="Deviation"
            desc={bodyByKey.get("Shape") ?? ""}
            value={data.deviation_class}
            valueColor={deviationColor(data.deviation_class)}
            valueSub={`z ${z != null ? fmtSigned(z, 2) : "—"} · ${
              pct != null ? `${fmtDecimal(pct, 0)}th` : "—"
            }`}
          />
          <Row
            label="Drive"
            desc={bodyByKey.get("Drive") ?? ""}
            value={data.drive_class}
            valueColor="var(--text-primary)"
            valueSub={data.regime}
          />
          <Row
            label="Spot–vol link"
            desc={bodyByKey.get("Spot–vol link") ?? ""}
            value={read.rho_confirms ? "CONFIRMED" : "NOT CONFIRMED"}
            valueColor={
              read.rho_confirms ? "var(--positive)" : "var(--text-primary)"
            }
          />
          <Row
            label="Relative value"
            desc={bodyByKey.get("Relative value") ?? ""}
            value={rvLabel(data.deviation_class)}
            valueColor={deviationColor(data.deviation_class)}
            last
          />
        </div>

        {/* Right: evidence behind the lean */}
        <div className="metric-card" style={{ padding: "12px 16px" }}>
          <div
            style={{
              ...labelStyle,
              letterSpacing: "0.1em",
              marginBottom: "8px",
            }}
          >
            Evidence
          </div>
          <div style={{ display: "flex", alignItems: "baseline", gap: "8px" }}>
            <span
              style={{
                ...valueStyle,
                fontSize: "16px",
                color: leanColor(lean.lean),
              }}
            >
              {leanLabel(lean.lean)}
            </span>
            <span
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: "10px",
                color: "var(--text-muted)",
              }}
            >
              confidence: {lean.confidence}
            </span>
            {evidence.status ? (
              <span
                data-testid="skew-lean-status"
                style={{
                  marginLeft: "auto",
                  flexShrink: 0,
                  fontFamily: "var(--font-mono)",
                  fontSize: "9px",
                  textTransform: "uppercase",
                  letterSpacing: "0.08em",
                  color: "var(--positive)",
                  background:
                    "color-mix(in srgb, var(--positive) 14%, transparent)",
                  border:
                    "1px solid color-mix(in srgb, var(--positive) 40%, transparent)",
                  borderRadius: "3px",
                  padding: "1px 6px",
                }}
              >
                {evidence.status}
              </span>
            ) : null}
          </div>
          <div
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: "11px",
              color: "var(--text-secondary)",
              marginTop: "6px",
              marginBottom: "10px",
              lineHeight: 1.5,
            }}
            data-testid="skew-lean-basis"
          >
            {evidence.lines.map((line, i) => (
              <div key={i}>{line}</div>
            ))}
          </div>
          <div
            style={{
              borderTop: "1px solid var(--border-dim, var(--line-grid))",
              paddingTop: "8px",
            }}
          >
            <EvidenceRow label="borrow" value={data.borrow_flag} />
            <EvidenceRow label="earnings" value={read.earnings_gate} />
            <EvidenceRow label="express" value={lean.express || "—"} />
            <EvidenceRow label="regime" value={data.regime} />
            {lean.structure_detail ? (
              <StructureDetail detail={lean.structure_detail} />
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}
