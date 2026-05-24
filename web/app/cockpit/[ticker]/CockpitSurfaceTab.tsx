import type { CockpitStateResponse, CockpitSurfaceResponse } from "@/lib/api";
import { useMemo } from "react";
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
  stateData,
}: {
  ticker: string;
  data: CockpitSurfaceResponse | null;
  stateData?: CockpitStateResponse | null;
}) {
  const skew = useMemo(() => data?.skew ?? [], [data?.skew]);
  const term = useMemo(() => data?.term ?? [], [data?.term]);
  const skewPoints = useMemo(
    () =>
      skew.map((point) => ({
        x: new Date(point.market_date).getTime(),
        y: toNum(point.risk_reversal),
      })),
    [skew],
  );
  const termPoints = useMemo(
    () =>
      term
        .map((point) => ({
          x: toNum(point.dte) ?? new Date(point.expiry).getTime(),
          y: toNum(point.volatility),
        }))
        .filter((point) => point.x != null),
    [term],
  );
  const skewSeries = useMemo(
    () => [
      {
        label: "25 delta RR",
        color: "var(--accent-bg)",
        points: skewPoints,
      },
    ],
    [skewPoints],
  );
  const termSeries = useMemo(
    () => [
      {
        label: "ATM IV",
        color: "var(--warning)",
        points: termPoints,
      },
    ],
    [termPoints],
  );

  if (!data) {
    return (
      <section style={panelStyle}>
        <h2 style={panelTitleStyle}>{ticker} Surface</h2>
        <div style={emptyStyle}>NO SURFACE ROWS</div>
      </section>
    );
  }

  const state = stateData?.state ?? null;

  return (
    <div style={{ display: "grid", gap: 16 }}>
      {state ? (
        <section style={panelStyle}>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
              gap: 10,
            }}
          >
            <Metric
              label="TERM CLASSIFICATION"
              value={formatLabel(state.term_classification)}
            />
            <Metric
              label="TERM STATE"
              value={formatLabel(state.term_state)}
            />
            <Metric
              label="SKEW Z 180D"
              value={fmtSigned(toNum(state.skew_25d_zscore_180d), 2)}
            />
            <Metric
              label="SKEW 5D CHANGE"
              value={fmtSigned(toNum(state.skew_25d_5d_change), 2)}
            />
            <Metric label="SKEW REGIME" value={formatLabel(state.skew_regime)} />
            <Metric
              label="SKEW TERM"
              value={fmtSigned(toNum(state.skew_term_structure), 2)}
            />
            <Metric
              label="SINGLE BUMP"
              value={fmtSigned(toNum(state.single_point_bump_pct), 2)}
            />
            <Metric
              label="FRONT/BACK SPREAD"
              value={fmtSigned(toNum(state.front_back_spread), 2)}
            />
            <Metric
              label="CURVE SLOPE"
              value={fmtSigned(toNum(state.full_curve_slope_pct), 2)}
            />
            <Metric
              label="JOHNSON SLOPE"
              value={fmtSigned(toNum(state.term_johnson_slope_pc1), 2)}
            />
          </div>
        </section>
      ) : null}

      <section style={panelStyle}>
        <h2 style={panelTitleStyle}>Skew Timeline</h2>
        <MultiLineChart
          series={skewSeries}
          xLabel={(x) => new Date(x).toISOString().slice(5, 10)}
        />
      </section>

      <section style={panelStyle}>
        <h2 style={panelTitleStyle}>Term Curve</h2>
        <MultiLineChart
          series={termSeries}
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
                <th style={thStyle}>E|Move|</th>
              </tr>
            </thead>
            <tbody>
              {skew.slice(-8).map((point, index) => (
                <tr key={`skew-${point.market_date}-${index}`}>
                  <td style={tdStyle}>Skew</td>
                  <td style={tdStyle}>{point.market_date}</td>
                  <td style={tdStyle}>{point.expiry ?? "-"}</td>
                  <td style={tdStyle}>-</td>
                  <td style={tdStyle}>
                    {fmtSigned(toNum(point.risk_reversal), 4)}
                  </td>
                  <td style={tdStyle}>-</td>
                  <td style={tdStyle}>-</td>
                </tr>
              ))}
              {term.map((point, index) => (
                <tr key={`term-${point.expiry}-${index}`}>
                  <td style={tdStyle}>Term</td>
                  <td style={tdStyle}>{data.market_date}</td>
                  <td style={tdStyle}>{point.expiry}</td>
                  <td style={tdStyle}>{point.dte ?? "-"}</td>
                  <td style={tdStyle}>{fmtDecimal(toNum(point.volatility), 4)}</td>
                  <td style={tdStyle}>
                    {fmtDecimal(toNum(point.implied_move_perc), 2)}
                  </td>
                  <td style={tdStyle}>
                    {fmtDecimal(toNum(point.implied_move_expected_abs), 4)}
                  </td>
                </tr>
              ))}
              {!skew.length && !term.length ? (
                <tr>
                  <td style={tdStyle} colSpan={7}>
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

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div
      style={{
        border: "1px solid var(--border-dim)",
        background: "var(--bg-panel-raised)",
        padding: 12,
        minHeight: 72,
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
          fontSize: 18,
          fontWeight: 800,
          letterSpacing: 0,
        }}
      >
        {value}
      </div>
    </div>
  );
}

function formatLabel(value: string | null | undefined): string {
  return value ? value.replaceAll("_", " ").toUpperCase() : "-";
}

const emptyStyle: React.CSSProperties = {
  display: "grid",
  minHeight: 180,
  placeItems: "center",
  color: "var(--text-muted)",
  fontFamily: "var(--font-mono)",
  fontSize: 11,
};
