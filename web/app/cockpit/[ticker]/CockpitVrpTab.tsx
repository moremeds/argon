import type { CockpitStateResponse, CockpitVrpResponse } from "@/lib/api";
import type React from "react";
import { fmtDecimal, fmtSigned, toNum } from "@/lib/formatters";
import {
  MultiLineChart,
  panelStyle,
  panelTitleStyle,
  tableStyle,
  tdStyle,
  thStyle,
} from "./CockpitChart";

export function CockpitVrpTab({
  ticker,
  data,
  stateData,
}: {
  ticker: string;
  data: CockpitVrpResponse | null;
  stateData?: CockpitStateResponse | null;
}) {
  if (!data) {
    return (
      <section style={panelStyle}>
        <h2 style={panelTitleStyle}>{ticker} VRP</h2>
        <div style={emptyStyle}>NO VRP ROWS</div>
      </section>
    );
  }

  const points = data.points ?? [];
  const vrpValues = points
    .map((point) => toNum(point.vrp))
    .filter((value): value is number => value != null);
  const stats = meanStd(vrpValues);
  const band =
    stats.std > 0
      ? {
          min: stats.mean - 0.5 * stats.std,
          max: stats.mean + 0.5 * stats.std,
          color: "rgba(245,166,35,0.12)",
        }
      : undefined;
  const latest = points[points.length - 1] ?? null;
  const state = stateData?.state ?? null;

  return (
    <div style={{ display: "grid", gap: 16 }}>
      <section style={panelStyle}>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
            gap: 10,
            marginBottom: 14,
          }}
        >
          <Metric label="VRP" value={fmtSigned(toNum(latest?.vrp), 4)} />
          <Metric label="IV" value={fmtDecimal(toNum(latest?.iv), 4)} />
          <Metric label="RV" value={fmtDecimal(toNum(latest?.rv), 4)} />
          <Metric
            label="IV rank"
            value={fmtDecimal(toNum(latest?.iv_rank_1y), 2)}
          />
          <Metric
            label="VRP Z 60D"
            value={fmtSigned(toNum(state?.vrp_zscore_60d), 2)}
          />
          <Metric
            label="VRP Z 252D"
            value={fmtSigned(toNum(state?.vrp_zscore_252d), 2)}
          />
          <Metric
            label="SIGN FLIP"
            value={formatSignFlip(
              state?.vrp_sign_flip_status,
              state?.vrp_sign_flip_aligned_days,
            )}
          />
        </div>
        <h2 style={panelTitleStyle}>VRP Timeline</h2>
        <MultiLineChart
          band={band}
          series={[
            {
              label: "IV - RV",
              color: "var(--accent-bg)",
              points: points.map((point) => ({
                x: new Date(point.market_date).getTime(),
                y: toNum(point.vrp),
              })),
            },
            {
              label: "IV",
              color: "var(--warning)",
              points: points.map((point) => ({
                x: new Date(point.market_date).getTime(),
                y: toNum(point.iv),
              })),
            },
            {
              label: "RV",
              color: "var(--negative)",
              points: points.map((point) => ({
                x: new Date(point.market_date).getTime(),
                y: toNum(point.rv),
              })),
            },
          ]}
          xLabel={(x) => new Date(x).toISOString().slice(5, 10)}
        />
      </section>

      <section style={panelStyle}>
        <h2 style={panelTitleStyle}>VRP Rows</h2>
        <div style={{ overflowX: "auto" }}>
          <table style={tableStyle}>
            <thead>
              <tr>
                <th style={thStyle}>Date</th>
                <th style={thStyle}>IV</th>
                <th style={thStyle}>RV</th>
                <th style={thStyle}>VRP</th>
                <th style={thStyle}>Z</th>
                <th style={thStyle}>IV rank</th>
              </tr>
            </thead>
            <tbody>
              {points.slice(-18).map((point) => {
                const vrp = toNum(point.vrp);
                const z =
                  vrp != null && stats.std > 0
                    ? (vrp - stats.mean) / stats.std
                    : null;
                return (
                  <tr key={point.market_date}>
                    <td style={tdStyle}>{point.market_date}</td>
                    <td style={tdStyle}>{fmtDecimal(toNum(point.iv), 4)}</td>
                    <td style={tdStyle}>{fmtDecimal(toNum(point.rv), 4)}</td>
                    <td style={tdStyle}>{fmtSigned(vrp, 4)}</td>
                    <td style={tdStyle}>{fmtSigned(z, 2)}</td>
                    <td style={tdStyle}>
                      {fmtDecimal(toNum(point.iv_rank_1y), 2)}
                    </td>
                  </tr>
                );
              })}
              {!points.length ? (
                <tr>
                  <td style={tdStyle} colSpan={6}>
                    -
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function formatSignFlip(
  status: boolean | "insufficient_history" | undefined,
  alignedDays: number | undefined,
): string {
  const suffix = alignedDays == null ? "" : ` ${alignedDays}/30`;
  if (status === true) return `YES${suffix}`;
  if (status === false) return `NO${suffix}`;
  if (status === "insufficient_history") return `INSUFFICIENT${suffix}`;
  return "-";
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div
      style={{
        border: "1px solid var(--border-dim)",
        background: "var(--bg-panel-raised)",
        padding: 12,
        minHeight: 76,
      }}
    >
      <div
        style={{
          color: "var(--text-muted)",
          fontFamily: "var(--font-mono)",
          fontSize: 10,
          letterSpacing: 1.2,
          textTransform: "uppercase",
        }}
      >
        {label}
      </div>
      <div
        style={{
          marginTop: 8,
          color: "var(--text-primary)",
          fontFamily: "var(--font-mono)",
          fontSize: 20,
          fontWeight: 800,
          letterSpacing: 0,
        }}
      >
        {value}
      </div>
    </div>
  );
}

function meanStd(values: number[]) {
  if (!values.length) return { mean: 0, std: 0 };
  const mean = values.reduce((sum, value) => sum + value, 0) / values.length;
  const variance =
    values.reduce((sum, value) => sum + (value - mean) ** 2, 0) / values.length;
  return { mean, std: Math.sqrt(variance) };
}

const emptyStyle: React.CSSProperties = {
  display: "grid",
  minHeight: 180,
  placeItems: "center",
  color: "var(--text-muted)",
  fontFamily: "var(--font-mono)",
  fontSize: 11,
};
