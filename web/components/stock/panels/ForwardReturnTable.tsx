"use client";

import { Fragment, useState } from "react";
import type { TechnicalsResponse } from "@/lib/api";
import { fmtPct } from "@/lib/formatters";
import { AnalyticalSeriesPanel } from "./AnalyticalSeriesPanel";

type Row = TechnicalsResponse["forward_returns"][number];

const HEADLINE_HORIZON = 40;

export function ForwardReturnTable({ data }: { data: TechnicalsResponse }) {
  const [showAll, setShowAll] = useState(false);
  const rows = data.forward_returns ?? [];
  const currentBand = data.header?.z_band ?? null;
  const horizons = showAll ? [20, 40, 60] : [HEADLINE_HORIZON];

  // band -> horizon -> row
  const byBand = new Map<string, Map<number, Row>>();
  for (const r of rows) {
    if (!byBand.has(r.band)) byBand.set(r.band, new Map());
    byBand.get(r.band)!.set(r.horizon, r);
  }
  // Preserve band order as first seen in the payload (already band-ordered).
  const bands = [...byBand.keys()];

  if (rows.length === 0) {
    return (
      <AnalyticalSeriesPanel
        title="Forward Return by Z-Band"
        subtitle="conditional edge"
      >
        <div style={{ color: "var(--text-muted)", fontSize: 12, padding: 8 }}>
          Not enough history yet for the conditioning table (need ~325 sessions;
          n={data.bars_n ?? 0}).
        </div>
      </AnalyticalSeriesPanel>
    );
  }

  const th: React.CSSProperties = {
    textAlign: "right",
    padding: "4px 10px",
    fontSize: 10,
    letterSpacing: 1,
    textTransform: "uppercase",
    color: "var(--text-muted)",
    borderBottom: "1px solid var(--border-dim)",
  };
  const td: React.CSSProperties = {
    textAlign: "right",
    padding: "4px 10px",
    fontSize: 12,
    fontVariantNumeric: "tabular-nums",
    color: "var(--text-primary)",
  };

  return (
    <AnalyticalSeriesPanel
      title="Forward Return by Z-Band"
      subtitle="conditional edge"
      headline={showAll ? "20 / 40 / 60d" : `${HEADLINE_HORIZON}d`}
    >
      <div style={{ marginBottom: 8 }}>
        <button
          onClick={() => setShowAll((v) => !v)}
          style={{
            fontSize: 10,
            letterSpacing: 1,
            textTransform: "uppercase",
            color: "var(--text-muted)",
            background: "transparent",
            border: "1px solid var(--border-dim)",
            borderRadius: 3,
            padding: "2px 8px",
            cursor: "pointer",
          }}
        >
          {showAll ? "40d only" : "all horizons"}
        </button>
      </div>
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr>
              <th style={{ ...th, textAlign: "left" }}>Band</th>
              {horizons.map((hz) => (
                <th key={hz} style={th} colSpan={4}>
                  {hz}d — N · Mean · Med · Win%
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {bands.map((band) => {
              const isCurrent = band === currentBand;
              return (
                <tr
                  key={band}
                  style={
                    isCurrent
                      ? {
                          background: "var(--accent-bg)",
                          boxShadow: "inset 3px 0 0 var(--accent-vivid)",
                        }
                      : undefined
                  }
                >
                  <td
                    style={{
                      ...td,
                      textAlign: "left",
                      color: isCurrent
                        ? "var(--text-primary)"
                        : "var(--text-secondary)",
                      fontWeight: isCurrent ? 700 : 400,
                    }}
                  >
                    {band}
                  </td>
                  {horizons.map((hz) => {
                    const r = byBand.get(band)?.get(hz);
                    if (!r) {
                      return (
                        <td key={hz} style={td} colSpan={4}>
                          —
                        </td>
                      );
                    }
                    const winColor =
                      r.win_rate >= 0.55
                        ? "var(--positive)"
                        : r.win_rate <= 0.45
                          ? "var(--negative)"
                          : "var(--text-primary)";
                    return (
                      <Fragment key={hz}>
                        <td style={td}>{r.count}</td>
                        <td
                          style={{
                            ...td,
                            color:
                              r.mean >= 0
                                ? "var(--positive)"
                                : "var(--negative)",
                          }}
                        >
                          {fmtPct(r.mean)}
                        </td>
                        <td style={td}>{fmtPct(r.median)}</td>
                        <td style={{ ...td, color: winColor }}>
                          {fmtPct(r.win_rate * 100, 0)}
                        </td>
                      </Fragment>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 8 }}>
        N-day forward return conditioned on z-band, full available history (n=
        {data.bars_n ?? 0} bars); bands assigned ex-ante.
      </div>
    </AnalyticalSeriesPanel>
  );
}
