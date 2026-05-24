import type { CockpitFlowImResponse } from "@/lib/api";
import { useMemo } from "react";
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
  const alerts = useMemo(() => data?.alerts ?? [], [data?.alerts]);
  const impliedMoves = useMemo(
    () => data?.implied_moves ?? [],
    [data?.implied_moves],
  );
  const imSeries = useMemo(
    () =>
      impliedMoves.map((point) => ({
        x: new Date(point.market_date).getTime(),
        y: toNum(point.implied_move_perc),
      })),
    [impliedMoves],
  );
  const imChartSeries = useMemo(
    () => [
      {
        label: "IM %",
        color: "var(--accent-bg)",
        points: imSeries,
      },
    ],
    [imSeries],
  );

  if (!data) {
    return (
      <section style={panelStyle}>
        <h2 style={panelTitleStyle}>{ticker} Flow + IM</h2>
        <div style={emptyStyle}>NO FLOW ROWS</div>
      </section>
    );
  }

  return (
    <div style={{ display: "grid", gap: 16 }}>
      <section style={panelStyle}>
        <h2 style={panelTitleStyle}>Implied Move</h2>
        <MultiLineChart
          showZero={false}
          series={imChartSeries}
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
                <th style={thStyle}>Rule</th>
                <th style={thStyle}>Flags</th>
                <th style={thStyle}>Footprint</th>
                <th style={thStyle}>Confidence</th>
                <th style={thStyle}>Volume</th>
                <th style={thStyle}>OI</th>
              </tr>
            </thead>
            <tbody>
              {alerts.length ? (
                alerts.map((alert, index) => (
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
                    <td style={tdStyle}>{alert.alert_rule ?? "-"}</td>
                    <td style={tdStyle}>{formatFlowFlags(alert)}</td>
                    <td style={tdStyle}>
                      {formatLabel(alert.flow_footprint_label)}
                    </td>
                    <td style={tdStyle}>
                      {fmtDecimal(toNum(alert.aggressor_label_confidence), 2)}
                    </td>
                    <td style={tdStyle}>{fmtDecimal(toNum(alert.volume), 0)}</td>
                    <td style={tdStyle}>
                      {fmtDecimal(toNum(alert.open_interest), 0)}
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td style={tdStyle} colSpan={11}>
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
                <th style={thStyle}>E|Move|</th>
                <th style={thStyle}>Percentile</th>
              </tr>
            </thead>
            <tbody>
              {impliedMoves.slice(-12).map((point) => (
                <tr key={`${point.market_date}-${point.days}`}>
                  <td style={tdStyle}>{point.market_date}</td>
                  <td style={tdStyle}>{point.days}</td>
                  <td style={tdStyle}>{fmtDecimal(toNum(point.volatility), 4)}</td>
                  <td style={tdStyle}>
                    {fmtDecimal(toNum(point.implied_move_perc), 2)}
                  </td>
                  <td style={tdStyle}>
                    {fmtDecimal(toNum(point.implied_move_expected_abs), 4)}
                  </td>
                  <td style={tdStyle}>{fmtDecimal(toNum(point.percentile), 2)}</td>
                </tr>
              ))}
              {!impliedMoves.length ? (
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

function formatLabel(value: string | null | undefined): string {
  return value ? value.replaceAll("_", " ").toUpperCase() : "-";
}

function formatFlowFlags(
  alert: NonNullable<NonNullable<CockpitFlowImResponse>["alerts"]>[number],
): string {
  const flags = [];
  if (alert.has_sweep) flags.push("SWEEP");
  if (alert.has_floor) flags.push("FLOOR");
  if (alert.has_multileg) flags.push("MULTI");
  if (alert.all_opening_trades) flags.push("OPEN");
  return flags.length ? flags.join(" ") : "-";
}

const emptyStyle: React.CSSProperties = {
  display: "grid",
  minHeight: 180,
  placeItems: "center",
  color: "var(--text-muted)",
  fontFamily: "var(--font-mono)",
  fontSize: 11,
};
