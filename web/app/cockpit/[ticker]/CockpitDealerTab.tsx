import type { CockpitDealerResponse } from "@/lib/api";
import type React from "react";
import { fmtDecimal, toNum } from "@/lib/formatters";
import {
  MultiLineChart,
  panelStyle,
  panelTitleStyle,
  tableStyle,
  tdStyle,
  thStyle,
} from "./CockpitChart";

type DealerPoint = NonNullable<CockpitDealerResponse>["points"][number];

export function CockpitDealerTab({
  ticker,
  data,
}: {
  ticker: string;
  data: CockpitDealerResponse | null;
}) {
  if (!data) return <EmptyPanel ticker={ticker} />;

  const groups = groupByExpiry(data.points).slice(0, 6);
  const latest = data.points.slice(0, 12);

  return (
    <div style={{ display: "grid", gap: 16 }}>
      <section style={panelStyle}>
        <h2 style={panelTitleStyle}>Dealer</h2>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
            gap: 14,
          }}
        >
          {groups.length ? (
            groups.map(([expiry, points]) => (
              <div key={expiry} style={miniPanelStyle}>
                <div style={miniTitleStyle}>{expiry}</div>
                <MultiLineChart
                  height={174}
                  series={[
                    {
                      label: "Net vanna",
                      color: "var(--accent-bg)",
                      points: points.map((point) => ({
                        x: toNum(point.strike) ?? 0,
                        y: netValue(point, "vanna"),
                      })),
                    },
                    {
                      label: "Net charm",
                      color: "var(--warning)",
                      points: points.map((point) => ({
                        x: toNum(point.strike) ?? 0,
                        y: netValue(point, "charm"),
                      })),
                    },
                  ]}
                />
              </div>
            ))
          ) : (
            <div style={emptyStyle}>NO DEALER ROWS</div>
          )}
        </div>
      </section>

      <section style={panelStyle}>
        <h2 style={panelTitleStyle}>Strike Rows</h2>
        <div style={{ overflowX: "auto" }}>
          <table style={tableStyle}>
            <thead>
              <tr>
                <th style={thStyle}>Expiry</th>
                <th style={thStyle}>Strike</th>
                <th style={thStyle}>Call vanna</th>
                <th style={thStyle}>Put vanna</th>
                <th style={thStyle}>Call charm</th>
                <th style={thStyle}>Put charm</th>
              </tr>
            </thead>
            <tbody>
              {latest.length ? (
                latest.map((point, index) => (
                  <tr key={`${point.expiry}-${point.strike}-${index}`}>
                    <td style={tdStyle}>{point.expiry}</td>
                    <td style={tdStyle}>{fmtDecimal(toNum(point.strike), 2)}</td>
                    <td style={tdStyle}>
                      {fmtDecimal(toNum(point.call_vanna), 4)}
                    </td>
                    <td style={tdStyle}>{fmtDecimal(toNum(point.put_vanna), 4)}</td>
                    <td style={tdStyle}>
                      {fmtDecimal(toNum(point.call_charm), 4)}
                    </td>
                    <td style={tdStyle}>{fmtDecimal(toNum(point.put_charm), 4)}</td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td style={tdStyle} colSpan={6}>
                    -
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function groupByExpiry(points: DealerPoint[]): [string, DealerPoint[]][] {
  const map = new Map<string, DealerPoint[]>();
  for (const point of points) {
    const key = String(point.expiry);
    const rows = map.get(key) ?? [];
    rows.push(point);
    map.set(key, rows);
  }
  return Array.from(map.entries())
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([expiry, rows]) => [
      expiry,
      rows
        .slice()
        .sort((a, b) => (toNum(a.strike) ?? 0) - (toNum(b.strike) ?? 0)),
    ]);
}

function netValue(point: DealerPoint, kind: "vanna" | "charm"): number | null {
  const callExposure =
    kind === "vanna"
      ? toNum(point.exposure_call_vanna)
      : toNum(point.exposure_call_charm);
  const putExposure =
    kind === "vanna"
      ? toNum(point.exposure_put_vanna)
      : toNum(point.exposure_put_charm);
  if (callExposure != null || putExposure != null) {
    return (callExposure ?? 0) + (putExposure ?? 0);
  }
  const callRaw = kind === "vanna" ? toNum(point.call_vanna) : toNum(point.call_charm);
  const putRaw = kind === "vanna" ? toNum(point.put_vanna) : toNum(point.put_charm);
  if (callRaw == null && putRaw == null) return null;
  return (callRaw ?? 0) + (putRaw ?? 0);
}

function EmptyPanel({ ticker }: { ticker: string }) {
  return (
    <section style={panelStyle}>
      <h2 style={panelTitleStyle}>{ticker} Dealer</h2>
      <div style={emptyStyle}>NO DEALER ROWS</div>
    </section>
  );
}

const miniPanelStyle: React.CSSProperties = {
  border: "1px solid var(--border-dim)",
  background: "var(--bg-panel-raised)",
  padding: 12,
};

const miniTitleStyle: React.CSSProperties = {
  color: "var(--text-secondary)",
  fontFamily: "var(--font-mono)",
  fontSize: 11,
  fontWeight: 800,
  marginBottom: 8,
};

const emptyStyle: React.CSSProperties = {
  display: "grid",
  minHeight: 180,
  placeItems: "center",
  color: "var(--text-muted)",
  fontFamily: "var(--font-mono)",
  fontSize: 11,
};
