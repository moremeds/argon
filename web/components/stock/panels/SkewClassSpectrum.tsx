"use client";

import { AnalyticalSeriesPanel } from "./AnalyticalSeriesPanel";

function prettySign(s: string): string {
  if (s === "put_skew") return "put-skew";
  if (s === "call_skew") return "call-skew";
  return s; // mixed | flat | unknown
}

export function SkewClassSpectrum({
  assetClass,
  expectedSign,
  actualSign,
}: {
  assetClass: string;
  expectedSign: string;
  actualSign: string; // put_skew | call_skew | flat | unknown (from rr_25d sign)
}) {
  const matches = expectedSign === actualSign || expectedSign === "mixed";
  return (
    <AnalyticalSeriesPanel title="Asset Class" subtitle="WHERE IT SITS">
      <div style={{ fontFamily: "var(--font-mono)", fontSize: 12 }}>
        <span style={{ color: "var(--accent-bg)", fontWeight: 700 }}>
          {assetClass}
        </span>
        <span style={{ color: "var(--text-muted)" }}>
          {" "}
          — expected {prettySign(expectedSign)}
        </span>
        <span
          style={{
            color: matches ? "var(--text-secondary)" : "var(--warning)",
            marginLeft: 8,
          }}
        >
          · actual {prettySign(actualSign)}
          {matches ? "" : " (divergent)"}
        </span>
      </div>
    </AnalyticalSeriesPanel>
  );
}
