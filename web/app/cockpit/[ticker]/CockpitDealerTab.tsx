import type { CockpitDealerResponse } from "@/lib/api";
import { useMemo } from "react";
import type React from "react";
import { fmtDecimal, fmtMoney, fmtSigned, toNum } from "@/lib/formatters";
import {
  MultiLineChart,
  panelStyle,
  panelTitleStyle,
  tableStyle,
  tdStyle,
  thStyle,
} from "./CockpitChart";

type DealerPoint = NonNullable<NonNullable<CockpitDealerResponse>["points"]>[number];
type DealerMetrics = NonNullable<NonNullable<CockpitDealerResponse>["metrics"]>;

export function CockpitDealerTab({
  ticker,
  data,
}: {
  ticker: string;
  data: CockpitDealerResponse | null;
}) {
  const points = useMemo(() => data?.points ?? [], [data?.points]);
  const metrics = useMemo(() => data?.metrics ?? {}, [data?.metrics]);
  const groups = useMemo(() => groupByExpiry(points).slice(0, 6), [points]);
  const primaryGroup = groups[0] ?? null;
  const primaryExpiry = primaryGroup?.[0] ?? null;
  const primaryPoints = useMemo(() => primaryGroup?.[1] ?? [], [primaryGroup]);
  const primaryTotals = useMemo(() => totals(primaryPoints), [primaryPoints]);
  const primaryPeaks = useMemo(() => peaks(primaryPoints), [primaryPoints]);
  const expirySummaries = useMemo(
    () =>
      groups.map(([expiry, points]) => ({
        expiry,
        count: points.length,
        ...totals(points),
        ...peaks(points),
      })),
    [groups],
  );
  const latest = useMemo(() => points.slice(0, 12), [points]);
  const vannaSeries = useMemo(
    () => [
      {
        label: "Call vanna",
        color: "var(--accent-bg)",
        points: primaryPoints.map((point) => ({
          x: toNum(point.strike) ?? 0,
          y: exposureValue(point, "call", "vanna"),
        })),
      },
      {
        label: "Put vanna",
        color: "var(--negative)",
        points: primaryPoints.map((point) => ({
          x: toNum(point.strike) ?? 0,
          y: exposureValue(point, "put", "vanna"),
        })),
      },
      {
        label: "Net vanna",
        color: "var(--warning)",
        points: primaryPoints.map((point) => ({
          x: toNum(point.strike) ?? 0,
          y: netValue(point, "vanna"),
        })),
      },
    ],
    [primaryPoints],
  );
  const charmSeries = useMemo(
    () => [
      {
        label: "Call charm",
        color: "var(--accent-bg)",
        points: primaryPoints.map((point) => ({
          x: toNum(point.strike) ?? 0,
          y: exposureValue(point, "call", "charm"),
        })),
      },
      {
        label: "Put charm",
        color: "var(--negative)",
        points: primaryPoints.map((point) => ({
          x: toNum(point.strike) ?? 0,
          y: exposureValue(point, "put", "charm"),
        })),
      },
      {
        label: "Net charm",
        color: "var(--warning)",
        points: primaryPoints.map((point) => ({
          x: toNum(point.strike) ?? 0,
          y: netValue(point, "charm"),
        })),
      },
    ],
    [primaryPoints],
  );

  if (!data) return <EmptyPanel ticker={ticker} />;

  return (
    <div style={{ display: "grid", gap: 16 }}>
      <section style={panelStyle}>
        <h2 style={panelTitleStyle}>Dealer</h2>
        <SignalGrid metrics={metrics} marketDate={data.market_date} />
        {primaryExpiry ? (
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
              gap: 10,
              marginBottom: 14,
            }}
          >
            <Metric label="Expiry" value={primaryExpiry} />
            <Metric label="Net vanna" value={fmtSigned(primaryTotals.vanna, 0)} />
            <Metric label="Net charm" value={fmtSigned(primaryTotals.charm, 0)} />
            <Metric
              label="Peak vanna strike"
              value={fmtDecimal(primaryPeaks.vannaStrike, 0)}
            />
            <Metric
              label="Peak charm strike"
              value={fmtDecimal(primaryPeaks.charmStrike, 0)}
            />
          </div>
        ) : null}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(360px, 1fr))",
            gap: 14,
            marginBottom: 14,
          }}
        >
          <div style={miniPanelStyle}>
            <div style={miniTitleStyle}>Vanna by strike</div>
            <MultiLineChart
              height={230}
              series={vannaSeries}
              assumeSorted
            />
          </div>
          <div style={miniPanelStyle}>
            <div style={miniTitleStyle}>Charm by strike</div>
            <MultiLineChart
              height={230}
              series={charmSeries}
              assumeSorted
            />
          </div>
        </div>
      </section>

      <section style={panelStyle}>
        <h2 style={panelTitleStyle}>Expiry Summary</h2>
        <div style={{ overflowX: "auto" }}>
          <table style={tableStyle}>
            <thead>
              <tr>
                <th style={thStyle}>Expiry</th>
                <th style={thStyle}>Strikes</th>
                <th style={thStyle}>Net vanna</th>
                <th style={thStyle}>Peak vanna strike</th>
                <th style={thStyle}>Net charm</th>
                <th style={thStyle}>Peak charm strike</th>
              </tr>
            </thead>
            <tbody>
              {expirySummaries.length ? (
                expirySummaries.map((row) => (
                  <tr key={row.expiry}>
                    <td style={tdStyle}>{row.expiry}</td>
                    <td style={tdStyle}>{fmtDecimal(row.count, 0)}</td>
                    <td style={tdStyle}>{fmtSigned(row.vanna, 0)}</td>
                    <td style={tdStyle}>{fmtDecimal(row.vannaStrike, 0)}</td>
                    <td style={tdStyle}>{fmtSigned(row.charm, 0)}</td>
                    <td style={tdStyle}>{fmtDecimal(row.charmStrike, 0)}</td>
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
                <th style={thStyle}>Net vanna</th>
                <th style={thStyle}>Net charm</th>
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
                    <td style={tdStyle}>{fmtSigned(netValue(point, "vanna"), 0)}</td>
                    <td style={tdStyle}>{fmtSigned(netValue(point, "charm"), 0)}</td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td style={tdStyle} colSpan={8}>
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

function SignalGrid({
  metrics,
  marketDate,
}: {
  metrics: Partial<DealerMetrics>;
  marketDate: string;
}) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
        gap: 10,
        marginBottom: 14,
      }}
    >
      <Metric label="Pin strike" value={formatPinCandidate(metrics)} />
      <Metric
        label="Pin source"
        value={formatPinSource(metrics.pin_source_date, marketDate)}
      />
      <Metric
        label="Pin sigma"
        value={formatWithSuffix(toNum(metrics.pin_distance_sigma), "sigma", 2)}
      />
      <Metric label="Pin regime" value={formatPinRegime(metrics.pin_regime_flag)} />
      <Metric
        label="Vanna proxy"
        value={fmtSigned(toNum(metrics.dealer_net_vanna_proxy), 0)}
      />
      <Metric
        label="Charm proxy"
        value={fmtSigned(toNum(metrics.dealer_net_charm_proxy), 0)}
      />
      <Metric label="Flow 3d" value={formatFlowColor(metrics.flow_color_lookback_3d)} />
      <Metric
        label="Put premium 3d"
        value={fmtMoney(toNum(metrics.flow_put_premium_3d))}
      />
      <Metric
        label="Call premium 3d"
        value={fmtMoney(toNum(metrics.flow_call_premium_3d))}
      />
      <Metric
        label="IV 30d delta 5d"
        value={formatVolPointDelta(toNum(metrics.iv_30d_delta_5d))}
      />
      <Metric
        label="Flow imbalance 3d"
        value={fmtSigned(toNum(metrics.directional_imbalance_3d), 0)}
      />
      <Metric
        label="Vanna reading"
        value={formatLabel(metrics.vanna_conditional_reading)}
      />
      <Metric
        label="Vanna OI bias"
        value={formatLabel(metrics.vanna_oi_change_bias)}
      />
      <Metric label="Net gamma" value={fmtSigned(toNum(metrics.net_gamma), 0)} />
      <Metric
        label="Gamma sign"
        value={formatGammaSign(metrics.net_gamma_sign)}
      />
      <Metric
        label="Gamma regime"
        value={formatGammaRegime(metrics.gamma_regime)}
      />
      <Metric label="Charm regime" value={formatLabel(metrics.charm_regime)} />
      <Metric
        label="Charm stress"
        value={
          metrics.charm_stress_override == null
            ? "—"
            : metrics.charm_stress_override
              ? "YES"
              : "NO"
        }
      />
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div
      style={{
        minHeight: 70,
        border: "1px solid var(--border-dim)",
        background: "var(--bg-panel-raised)",
        padding: 10,
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

function formatPinCandidate(metrics: Partial<DealerMetrics>): string {
  const strike = fmtDecimal(toNum(metrics.pin_candidate_strike), 0);
  if (!metrics.pin_candidate_expiry) return strike;
  if (strike === "—") return String(metrics.pin_candidate_expiry);
  return `${strike} @ ${metrics.pin_candidate_expiry}`;
}

function formatPinSource(
  sourceDate: string | null | undefined,
  marketDate: string,
): string {
  if (!sourceDate) return "NO OI SOURCE";
  return sourceDate === marketDate ? sourceDate : `${sourceDate} STALE`;
}

function formatWithSuffix(
  value: number | null,
  suffix: string,
  digits: number,
): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${fmtSigned(value, digits)} ${suffix}`;
}

function formatVolPointDelta(value: number | null): string {
  if (value == null || !Number.isFinite(value)) return "NO 5D BASELINE";
  return `${fmtSigned(value * 100, 1)} vol pts`;
}

function formatPinRegime(value: boolean | null | undefined): string {
  if (value == null) return "—";
  return value ? "ACTIVE" : "INACTIVE";
}

function formatFlowColor(value: DealerMetrics["flow_color_lookback_3d"]): string {
  if (!value) return "—";
  return value.replace("_", " ").toUpperCase();
}

function formatGammaSign(value: DealerMetrics["net_gamma_sign"]): string {
  if (!value) return "—";
  return value.toUpperCase();
}

function formatGammaRegime(value: DealerMetrics["gamma_regime"]): string {
  if (!value) return "—";
  return value.replace("_", " ").toUpperCase();
}

function formatLabel(value: string | null | undefined): string {
  return value ? value.replaceAll("_", " ").toUpperCase() : "—";
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

function totals(points: DealerPoint[]) {
  return points.reduce(
    (acc, point) => ({
      vanna: acc.vanna + (netValue(point, "vanna") ?? 0),
      charm: acc.charm + (netValue(point, "charm") ?? 0),
    }),
    { vanna: 0, charm: 0 },
  );
}

function peaks(points: DealerPoint[]) {
  const peakVanna = maxAbs(points, "vanna");
  const peakCharm = maxAbs(points, "charm");
  return {
    vannaStrike: peakVanna ? toNum(peakVanna.strike) : null,
    charmStrike: peakCharm ? toNum(peakCharm.strike) : null,
  };
}

function maxAbs(points: DealerPoint[], kind: "vanna" | "charm") {
  let best: DealerPoint | null = null;
  let bestMagnitude = -1;
  for (const point of points) {
    const value = netValue(point, kind);
    const magnitude = value == null ? -1 : Math.abs(value);
    if (magnitude > bestMagnitude) {
      best = point;
      bestMagnitude = magnitude;
    }
  }
  return best;
}

function exposureValue(
  point: DealerPoint,
  side: "call" | "put",
  kind: "vanna" | "charm",
): number | null {
  if (side === "call" && kind === "vanna") return toNum(point.exposure_call_vanna);
  if (side === "put" && kind === "vanna") return toNum(point.exposure_put_vanna);
  if (side === "call" && kind === "charm") return toNum(point.exposure_call_charm);
  return toNum(point.exposure_put_charm);
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
