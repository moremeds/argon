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

function rvLabel(cls: string): string {
  if (cls === "RICH") return "FADE / FINANCE";
  if (cls === "CHEAP") return "OWN OPTIONALITY";
  return "NO EDGE";
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

function ContextRow({ label, value }: { label: string; value: string }) {
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

// Descriptor only. The prior directional lean / forward-return "verdict" (and
// its "validated" badge and suggested option structure) was removed after the
// skew-directional probe found it carries no forward edge — the read was beta +
// momentum, the index verdict even sign-inverted, and "validated" was false
// confidence from a bull-only sample. Skew still legitimately describes *current
// positioning*, which is all this panel now claims.
// See docs/research/skew-directional/README.md.
export function SkewSignalDetail({ data }: { data: SkewAnalysisResponse }) {
  const read = data.read;
  // Explanation prose comes from the backend-built bullets (single source of
  // truth, unit-tested); look up each body by its label prefix so we don't
  // depend on array order.
  const bodyByKey = new Map<string, string>();
  for (const b of read.summary_bullets ?? []) {
    bodyByKey.set((b.label ?? "").split(" — ")[0], b.body ?? "");
  }
  const z = toNum(data.rr_z_180d);
  const pct = toNum(data.rr_pct_252d);

  return (
    <div className="section" data-testid="skew-signal-detail">
      <div className="section-header">
        <div className="section-title">
          <Zap size={14} />
          Skew Read
          <InfoTooltip text="Descriptive read of current options positioning: how 25Δ skew deviates from the ticker's own baseline, what's driving it, whether spot–vol corroborates, and the rich/cheap relative-value implication. This describes positioning as it stands — it is not a forecast of forward returns." />
        </div>
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

        {/* Right: factual context for the setup — not a forecast */}
        <div className="metric-card" style={{ padding: "12px 16px" }}>
          <div
            style={{
              ...labelStyle,
              letterSpacing: "0.1em",
              marginBottom: "8px",
            }}
          >
            Context
          </div>
          <ContextRow label="borrow" value={data.borrow_flag} />
          <ContextRow label="earnings" value={read.earnings_gate} />
          <ContextRow label="regime" value={data.regime} />
        </div>
      </div>
    </div>
  );
}
