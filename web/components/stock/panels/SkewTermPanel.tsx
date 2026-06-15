"use client";

import { fmtSigned, toNum } from "@/lib/formatters";

import { AnalyticalSeriesPanel } from "./AnalyticalSeriesPanel";

export function SkewTermPanel({
  termClass,
  frontRr,
  backRr,
}: {
  termClass: string;
  frontRr?: string | number | null;
  backRr?: string | number | null;
}) {
  const f = toNum(frontRr);
  const b = toNum(backRr);
  return (
    <AnalyticalSeriesPanel title="Skew Term" subtitle="FRONT vs BACK">
      {b == null ? (
        <div style={{ color: "var(--text-muted)", fontSize: 11 }}>
          Single expiry on file — term structure unavailable ({termClass}).
        </div>
      ) : (
        <div
          style={{ display: "flex", gap: 24, fontFamily: "var(--font-mono)" }}
        >
          <div>
            <div style={{ fontSize: 10, color: "var(--text-muted)" }}>
              FRONT
            </div>
            <div style={{ fontSize: 18 }}>
              {f != null ? fmtSigned(f, 4) : "—"}
            </div>
          </div>
          <div>
            <div style={{ fontSize: 10, color: "var(--text-muted)" }}>BACK</div>
            <div style={{ fontSize: 18 }}>{fmtSigned(b, 4)}</div>
          </div>
          <div>
            <div style={{ fontSize: 10, color: "var(--text-muted)" }}>
              CLASS
            </div>
            <div style={{ fontSize: 18 }}>{termClass}</div>
          </div>
        </div>
      )}
    </AnalyticalSeriesPanel>
  );
}
