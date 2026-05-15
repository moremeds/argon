import type { CockpitFlowImResponse } from "@/lib/api";
import type React from "react";
import {
  fmtDateTimeWithZone,
  fmtDecimal,
  fmtMoney,
  toNum,
} from "@/lib/formatters";
import {
  MultiLineChart,
  panelStyle,
  panelTitleStyle,
  tableStyle,
  tdStyle,
  thStyle,
} from "./CockpitChart";

export function CockpitFlowImTab({
  ticker,
  data,
}: {
  ticker: string;
  data: CockpitFlowImResponse | null;
}) {
  if (!data) {
    return (
      <section style={panelStyle}>
        <h2 style={panelTitleStyle}>{ticker} Flow + IM</h2>
        <div style={emptyStyle}>NO FLOW ROWS</div>
      </section>
    );
  }

  const imSeries = data.implied_moves.map((point) => ({
    x: new Date(point.market_date).getTime(),
    y: toNum(point.implied_move_perc),
  }));

  return (
    <div style={{ display: "grid", gap: 16 }}>
      <section style={panelStyle}>
        <h2 style={panelTitleStyle}>Implied Move</h2>
        <MultiLineChart
          showZero={false}
          series={[
            {
              label: "IM %",
              color: "var(--accent-bg)",
              points: imSeries,
            },
          ]}
          xLabel={(x) => new Date(x).toISOString().slice(5, 10)}
        />
      </section>

      <section style={panelStyle}>
        <h2 style={panelTitleStyle}>Flow Footprints</h2>
        <div style={{ overflowX: "auto" }}>
          <table style={tableStyle}>
            <thead>
              <tr>
                <th style={thStyle}>Created</th>
                <th style={thStyle}>Contract</th>
                <th style={thStyle}>Premium</th>
                <th style={thStyle}>Ask prem</th>
                <th style={thStyle}>Bid prem</th>
                <th style={thStyle}>Volume</th>
                <th style={thStyle}>OI</th>
              </tr>
            </thead>
            <tbody>
              {data.alerts.length ? (
                data.alerts.map((alert, index) => (
                  <tr key={`${alert.alert_id}-${index}`}>
                    <td style={tdStyle}>
                      {fmtDateTimeWithZone(alert.created_at).slice(0, 16)}
                    </td>
                    <td style={tdStyle}>
                      {alert.option_chain ??
                        `${alert.expiry ?? "-"} ${fmtDecimal(toNum(alert.strike), 1)} ${alert.option_type ?? ""}`}
                    </td>
                    <td style={tdStyle}>
                      {fmtMoney(toNum(alert.total_premium))}
                    </td>
                    <td style={tdStyle}>
                      {fmtMoney(toNum(alert.total_ask_side_prem))}
                    </td>
                    <td style={tdStyle}>
                      {fmtMoney(toNum(alert.total_bid_side_prem))}
                    </td>
                    <td style={tdStyle}>{fmtDecimal(toNum(alert.volume), 0)}</td>
                    <td style={tdStyle}>
                      {fmtDecimal(toNum(alert.open_interest), 0)}
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td style={tdStyle} colSpan={7}>
                    -
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section style={panelStyle}>
        <h2 style={panelTitleStyle}>IM Rows</h2>
        <div style={{ overflowX: "auto" }}>
          <table style={tableStyle}>
            <thead>
              <tr>
                <th style={thStyle}>Date</th>
                <th style={thStyle}>Days</th>
                <th style={thStyle}>Vol</th>
                <th style={thStyle}>IM %</th>
                <th style={thStyle}>Percentile</th>
              </tr>
            </thead>
            <tbody>
              {data.implied_moves.slice(-12).map((point) => (
                <tr key={`${point.market_date}-${point.days}`}>
                  <td style={tdStyle}>{point.market_date}</td>
                  <td style={tdStyle}>{point.days}</td>
                  <td style={tdStyle}>{fmtDecimal(toNum(point.volatility), 4)}</td>
                  <td style={tdStyle}>
                    {fmtDecimal(toNum(point.implied_move_perc), 2)}
                  </td>
                  <td style={tdStyle}>{fmtDecimal(toNum(point.percentile), 2)}</td>
                </tr>
              ))}
              {!data.implied_moves.length ? (
                <tr>
                  <td style={tdStyle} colSpan={5}>
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
