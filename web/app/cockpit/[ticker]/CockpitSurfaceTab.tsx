import type { CockpitSurfaceResponse } from "@/lib/api";
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

export function CockpitSurfaceTab({
  ticker,
  data,
}: {
  ticker: string;
  data: CockpitSurfaceResponse | null;
}) {
  if (!data) {
    return (
      <section style={panelStyle}>
        <h2 style={panelTitleStyle}>{ticker} Surface</h2>
        <div style={emptyStyle}>NO SURFACE ROWS</div>
      </section>
    );
  }

  const skewPoints = data.skew.map((point) => ({
    x: new Date(point.market_date).getTime(),
    y: toNum(point.risk_reversal),
  }));
  const termPoints = data.term
    .map((point) => ({
      x: toNum(point.dte) ?? new Date(point.expiry).getTime(),
      y: toNum(point.volatility),
    }))
    .filter((point) => point.x != null);

  return (
    <div style={{ display: "grid", gap: 16 }}>
      <section style={panelStyle}>
        <h2 style={panelTitleStyle}>Skew Timeline</h2>
        <MultiLineChart
          series={[
            {
              label: "25 delta RR",
              color: "var(--accent-bg)",
              points: skewPoints,
            },
          ]}
          xLabel={(x) => new Date(x).toISOString().slice(5, 10)}
        />
      </section>

      <section style={panelStyle}>
        <h2 style={panelTitleStyle}>Term Curve</h2>
        <MultiLineChart
          series={[
            {
              label: "ATM IV",
              color: "var(--warning)",
              points: termPoints,
            },
          ]}
          showZero={false}
          xLabel={(x) => `${Math.round(x)}d`}
        />
      </section>

      <section style={panelStyle}>
        <h2 style={panelTitleStyle}>Surface Rows</h2>
        <div style={{ overflowX: "auto" }}>
          <table style={tableStyle}>
            <thead>
              <tr>
                <th style={thStyle}>Kind</th>
                <th style={thStyle}>Date</th>
                <th style={thStyle}>Expiry</th>
                <th style={thStyle}>DTE</th>
                <th style={thStyle}>Value</th>
                <th style={thStyle}>IM %</th>
              </tr>
            </thead>
            <tbody>
              {data.skew.slice(-8).map((point, index) => (
                <tr key={`skew-${point.market_date}-${index}`}>
                  <td style={tdStyle}>Skew</td>
                  <td style={tdStyle}>{point.market_date}</td>
                  <td style={tdStyle}>{point.expiry ?? "-"}</td>
                  <td style={tdStyle}>-</td>
                  <td style={tdStyle}>
                    {fmtSigned(toNum(point.risk_reversal), 4)}
                  </td>
                  <td style={tdStyle}>-</td>
                </tr>
              ))}
              {data.term.map((point, index) => (
                <tr key={`term-${point.expiry}-${index}`}>
                  <td style={tdStyle}>Term</td>
                  <td style={tdStyle}>{data.market_date}</td>
                  <td style={tdStyle}>{point.expiry}</td>
                  <td style={tdStyle}>{point.dte ?? "-"}</td>
                  <td style={tdStyle}>{fmtDecimal(toNum(point.volatility), 4)}</td>
                  <td style={tdStyle}>
                    {fmtDecimal(toNum(point.implied_move_perc), 2)}
                  </td>
                </tr>
              ))}
              {!data.skew.length && !data.term.length ? (
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

const emptyStyle: React.CSSProperties = {
  display: "grid",
  minHeight: 180,
  placeItems: "center",
  color: "var(--text-muted)",
  fontFamily: "var(--font-mono)",
  fontSize: 11,
};
