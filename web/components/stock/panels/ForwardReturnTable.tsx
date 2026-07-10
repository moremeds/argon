"use client";

import { Fragment, useState } from "react";
import type { TechnicalsResponse } from "@/lib/api";
import { fmtPct } from "@/lib/formatters";
import { AnalyticalSeriesPanel } from "./AnalyticalSeriesPanel";

type Row = TechnicalsResponse["forward_returns"][number];

const HEADLINE_HORIZON = 40;

export function ForwardReturnTable({ data }: { data: TechnicalsResponse }) {
  const [showAll, setShowAll] = useState(true);
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
            {/* Row 1: horizon group label centered over its 4 columns.
                Row 2: per-column sub-headers, right-aligned to match the data
                cells so each label sits directly over its column. */}
            <tr>
              <th style={{ ...th, textAlign: "left" }} rowSpan={2}>
                Band
              </th>
              {horizons.map((hz, gi) => (
                <th
                  key={hz}
                  style={{
                    ...th,
                    textAlign: "center",
                    color: "var(--text-secondary)",
                    borderLeft:
                      gi > 0 ? "1px solid var(--border-dim)" : undefined,
                  }}
                  colSpan={4}
                >
                  {hz}d
                </th>
              ))}
            </tr>
            <tr>
              {horizons.map((hz, gi) => (
                <Fragment key={hz}>
                  <th
                    style={{
                      ...th,
                      borderLeft:
                        gi > 0 ? "1px solid var(--border-dim)" : undefined,
                    }}
                  >
                    N
                  </th>
                  <th style={th}>Mean</th>
                  <th style={th}>Med</th>
                  <th style={th}>Win%</th>
                </Fragment>
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
                  {horizons.map((hz, gi) => {
                    const groupBorder =
                      gi > 0 ? "1px solid var(--border-dim)" : undefined;
                    const r = byBand.get(band)?.get(hz);
                    if (!r) {
                      return (
                        <td
                          key={hz}
                          style={{ ...td, borderLeft: groupBorder }}
                          colSpan={4}
                        >
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
                        <td style={{ ...td, borderLeft: groupBorder }}>
                          {r.count}
                        </td>
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
                          {fmtPct(r.win_rate, 0)}
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
        <strong style={{ color: "var(--text-secondary)" }}>How to read:</strong>{" "}
        each row is a z-band — how stretched price was vs its 200-day average.
        For every past day the stock sat in that band, we measured its return{" "}
        <em>N</em> trading days later. <strong>N</strong> = how many such days
        (bigger = more reliable); <strong>Mean/Med</strong> = the average/median
        of those forward returns; <strong>Win%</strong> = share that were
        positive. Green mean = historically bullish from that band, red =
        bearish. The highlighted row is the band price sits in today — read it
        as &ldquo;last time we were here, this is what tended to happen
        next.&rdquo;
      </div>
      <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 6 }}>
        N-day forward return conditioned on z-band, full available history (n=
        {data.bars_n ?? 0} bars); bands assigned ex-ante. Not a forecast — past
        conditional behavior, small-N bands especially.
      </div>
    </AnalyticalSeriesPanel>
  );
}
