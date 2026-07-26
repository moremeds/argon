"use client";

// Fragment, not <>...</>: the map returns a fragment wrapping two <tr>s, and
// the key belongs on the returned element. React's jsx-key lint rule fails the
// shorthand, which cannot take a key.
import { Fragment, useState } from "react";
import { Layers } from "lucide-react";

import type {
  CrowdingBand,
  SectorCrowdingData,
  SectorCrowdingLeg,
  SectorCrowdingRow,
} from "@/lib/regime/useSectorCrowding";
import InfoTooltip from "./InfoTooltip";
import { SectorCrowdingCharts } from "./SectorCrowdingCharts";

const GUIDE =
  "Sector crowding (板块拥挤度), three conjunctive legs. PRICE = 63-session " +
  "return minus SPY's over the same sessions, shown raw with its own " +
  "trailing percentile. Absolute spread is not comparable across sectors — " +
  "the trailing SD of that spread runs from 3.1 (XLY) to 16.5 (XLE), so " +
  "ranking on it ranks volatility — and 63 sessions is ~3 months only where " +
  "UW's coverage is complete (~4.5 months for SOXX and IGV). " +
  "FLOW = 1M net flow / AUM on published bands (2% warm, 5% crowded, 10% " +
  "extreme); dividing by AUM already removes the size effect, so absolute " +
  "bands hold here. PREMIUM = iv_rank minus SPY's, standing in for the " +
  "source framework's NTM P/E, which needs constituent forward EPS we cannot " +
  "source. STATE is the WEAKEST leg's band, not the average — every leg we " +
  "have must fire for a row to read as crowded — and the arrow names the leg " +
  "holding it down. Two present legs is the minimum; below that the row is " +
  "blank rather than badged on a single reading.";

const BAND_COLOR: Record<CrowdingBand, string> = {
  CROWDED: "var(--negative, #ef4444)",
  WARM: "var(--warning, #f59e0b)",
  NORMAL: "var(--text-secondary, #94a3b8)",
  COLD: "var(--text-muted)",
};

const MONO = {
  fontFamily: "var(--font-mono)",
  fontSize: 11,
} as const;

// NOT lib/formatters.fmtSignedPct. That one takes a FRACTION and multiplies by
// 100 (formatters.ts:57), while every value on this panel is already in
// percentage points -- SOXX's price leg is 53.69, meaning 53.69%. Routing it
// through the shared helper renders "+5369.0%". Deliberately named differently
// so nobody "consolidates" the two. This is the scale trap web/CLAUDE.md
// flags: never trust scale, re-check the contract per tile.
function fmtPctPoints(v: number | null | undefined): string {
  if (v == null) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`;
}

function LegCell({
  leg,
  testId,
  showPercentile,
  suffix,
}: {
  leg: SectorCrowdingLeg;
  testId: string;
  showPercentile?: boolean;
  suffix?: string;
}) {
  const raw =
    leg.raw == null
      ? "—"
      : suffix === "pt"
        ? `${leg.raw >= 0 ? "+" : ""}${leg.raw.toFixed(0)}`
        : fmtPctPoints(leg.raw);
  return (
    <td style={{ ...MONO, textAlign: "right", padding: "3px 8px" }}>
      <span
        data-testid={testId}
        style={{ color: leg.band ? BAND_COLOR[leg.band] : "var(--text-muted)" }}
      >
        {raw}
        {showPercentile && leg.score != null && (
          <span style={{ color: "var(--text-muted)", fontSize: 9 }}>
            {` (${leg.score.toFixed(0)}ᵗʰ)`}
          </span>
        )}
      </span>
    </td>
  );
}

export function SectorCrowdingPanel({
  data,
}: {
  data: SectorCrowdingData | null;
}) {
  const [open, setOpen] = useState<string | null>(null);
  const rows = data?.rows ?? [];
  const benchmark = data?.benchmark ?? "SPY";

  if (!rows.length) {
    return (
      <div className="section" data-testid="sector-crowding-empty">
        <div className="section-header">
          <div className="section-title">
            <Layers size={14} />
            Sector Crowding
          </div>
        </div>
        <div
          className="section-body"
          style={{
            padding: 24,
            textAlign: "center",
            color: "var(--text-muted)",
            ...MONO,
          }}
        >
          No sector crowding data — the 18:45 ET capture has not run yet.
        </div>
      </div>
    );
  }

  const th = {
    ...MONO,
    fontSize: 10,
    letterSpacing: 1.5,
    textTransform: "uppercase" as const,
    color: "var(--text-muted)",
    textAlign: "right" as const,
    padding: "3px 8px",
    fontWeight: 400,
  };

  return (
    <div className="section" data-testid="sector-crowding-panel">
      <div className="section-header">
        <div className="section-title">
          <Layers size={14} />
          Sector Crowding{data?.as_of ? ` — ${data.as_of}` : ""}
          <InfoTooltip
            text={GUIDE}
            triggerTestId="sector-crowding-tooltip-trigger"
            contentTestId="sector-crowding-tooltip-content"
          />
        </div>
      </div>
      <div className="section-body">
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr>
              <th style={{ ...th, textAlign: "left" }}>ETF</th>
              <th style={th}>{`63d vs ${benchmark}`}</th>
              <th style={th}>1M Flow/AUM</th>
              <th style={th}>{`IVR Δ vs ${benchmark}`}</th>
              <th style={th}>Score</th>
              <th style={{ ...th, textAlign: "left" }}>State</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r: SectorCrowdingRow) => (
              <Fragment key={r.ticker}>
                <tr
                  data-testid={`sector-crowding-row-${r.ticker}`}
                  onClick={() =>
                    setOpen((cur) => (cur === r.ticker ? null : r.ticker))
                  }
                  style={{
                    cursor: "pointer",
                    borderTop: "1px solid var(--border-dim)",
                    background:
                      open === r.ticker ? "var(--bg-panel)" : "transparent",
                  }}
                >
                  <td style={{ ...MONO, padding: "3px 8px", fontWeight: 600 }}>
                    {r.ticker}
                  </td>
                  <LegCell
                    leg={r.price}
                    testId={`sector-crowding-price-${r.ticker}`}
                    showPercentile
                  />
                  <LegCell
                    leg={r.flow}
                    testId={`sector-crowding-flow-${r.ticker}`}
                  />
                  <LegCell
                    leg={r.premium}
                    testId={`sector-crowding-premium-${r.ticker}`}
                    suffix="pt"
                  />
                  <td
                    style={{ ...MONO, textAlign: "right", padding: "3px 8px" }}
                  >
                    {r.score == null ? "—" : r.score.toFixed(0)}
                  </td>
                  <td style={{ ...MONO, padding: "3px 8px" }}>
                    <span
                      data-testid={`sector-crowding-state-${r.ticker}`}
                      style={{
                        color: r.state
                          ? BAND_COLOR[r.state]
                          : "var(--text-muted)",
                      }}
                    >
                      {r.state ?? "—"}
                      {r.binding_leg && (
                        <span
                          style={{ color: "var(--text-muted)", fontSize: 9 }}
                        >
                          {` ← ${r.binding_leg}`}
                        </span>
                      )}
                    </span>
                  </td>
                </tr>
                {open === r.ticker && (
                  <tr>
                    <td colSpan={6} style={{ padding: 0 }}>
                      <SectorCrowdingCharts row={r} benchmark={benchmark} />
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default SectorCrowdingPanel;
