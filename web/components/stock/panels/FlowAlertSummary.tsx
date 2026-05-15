import type { components } from "@/lib/types";
import { fmtDecimal, fmtMoney, toNum } from "@/lib/formatters";

type Flow = components["schemas"]["FlowSnapshot"];
type Alert = components["schemas"]["FlowAlert"];

function alertCountLabel(flow: Flow): string {
  const suffix = flow.flow_count_is_limited ? "+" : "";
  return `${fmtDecimal(flow.flow_count, 0)}${suffix} alerts fetched`;
}

function topRule(alerts: Alert[]): string {
  const top = [...alerts].sort(
    (a, b) => (toNum(b.total_premium) ?? 0) - (toNum(a.total_premium) ?? 0),
  )[0];
  return top?.alert_rule ?? "—";
}

function baselineLabel(flow: Flow): string {
  const ratio = toNum(flow.flow_count_vs_30d_avg);
  if (ratio == null || !flow.flow_count_30d_days) {
    return "30d baseline building";
  }
  const prefix = flow.flow_count_is_limited ? ">=" : "";
  return `Alerts ${prefix}${ratio.toFixed(1)}x 30d avg`;
}

function hasBaseline(flow: Flow): boolean {
  return toNum(flow.flow_count_vs_30d_avg) != null && Boolean(flow.flow_count_30d_days);
}

function askBidLabel(flow: Flow): string {
  const ask = toNum(flow.ask_side_premium);
  const bid = toNum(flow.bid_side_premium);
  if (ask == null || bid == null || bid === 0) return "Ask/Bid —";
  return `Ask/Bid ${(ask / bid).toFixed(1)}x`;
}

export function FlowAlertSummary({ flow }: { flow: Flow }) {
  const alertPremium =
    (toNum(flow.bull_premium) ?? 0) + (toNum(flow.bear_premium) ?? 0);
  const items = [
    { label: alertCountLabel(flow), highlight: false },
    { label: `Top rule ${topRule(flow.top_alerts ?? [])}`, highlight: false },
    { label: `Premium ${fmtMoney(alertPremium)}`, highlight: false },
    { label: askBidLabel(flow), highlight: false },
    { label: baselineLabel(flow), highlight: true },
  ];
  const baselineReady = hasBaseline(flow);

  return (
    <div
      aria-label="Flow alert summary"
      style={{
        display: "flex",
        flexWrap: "wrap",
        gap: "8px 14px",
        fontFamily: "var(--font-mono)",
        fontSize: 11,
        color: "var(--text-muted)",
      }}
    >
      {items.map((item) => (
        <span
          key={item.label}
          data-highlight={item.highlight ? "baseline" : undefined}
          style={
            item.highlight
              ? {
                  color: baselineReady ? "var(--accent-warm)" : "var(--text-primary)",
                  border: `1px solid ${
                    baselineReady
                      ? "color-mix(in srgb, var(--accent-warm) 55%, transparent)"
                      : "var(--border-dim)"
                  }`,
                  background: baselineReady
                    ? "color-mix(in srgb, var(--accent-warm) 16%, transparent)"
                    : "var(--bg-panel)",
                  padding: "3px 7px",
                  borderRadius: 4,
                  fontWeight: 800,
                  lineHeight: 1,
                }
              : undefined
          }
        >
          {item.label}
        </span>
      ))}
    </div>
  );
}
