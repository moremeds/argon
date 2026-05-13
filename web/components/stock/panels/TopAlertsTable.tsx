import type { components } from "@/lib/types";
import { fmtDecimal, toNum } from "@/lib/formatters";
import { describeAlertRule, UW_ALERT_RULES } from "@/lib/uw-alert-rules";

type Alert = components["schemas"]["FlowAlert"];

export function TopAlertsTable({ alerts }: { alerts: Alert[] }) {
  const rows = [...alerts]
    .sort(
      (a, b) => (toNum(b.total_premium) ?? 0) - (toNum(a.total_premium) ?? 0),
    )
    .slice(0, 10);

  return (
    <table
      style={{
        width: "100%",
        borderCollapse: "collapse",
        fontFamily: "var(--font-mono)",
        fontSize: 12,
      }}
    >
      <thead>
        <tr style={{ color: "var(--text-muted)", textAlign: "left" }}>
          <th>ID</th>
          <th>
            RULE
            <details
              style={{
                display: "inline-block",
                marginLeft: 4,
                position: "relative",
              }}
            >
              <summary
                aria-label="Rule glossary"
                style={{ listStyle: "none", cursor: "help" }}
              >
                (i)
              </summary>
              <div
                style={{
                  position: "absolute",
                  zIndex: 10,
                  background: "var(--bg-panel)",
                  border: "1px solid var(--border-dim)",
                  padding: 8,
                  maxWidth: 360,
                  fontSize: 11,
                  color: "var(--text-primary)",
                }}
              >
                <ul style={{ margin: 0, paddingLeft: 16 }}>
                  {Object.entries(UW_ALERT_RULES).map(([slug, desc]) => (
                    <li key={slug}>
                      <strong>{slug}</strong>: {desc}
                    </li>
                  ))}
                </ul>
              </div>
            </details>
          </th>
          <th>PREMIUM</th>
          <th>VOL/OI</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((a) => (
          <tr key={a.id} style={{ borderTop: "1px solid var(--border-dim)" }}>
            <td>{a.id?.slice(0, 8)}</td>
            <td title={describeAlertRule(a.alert_rule ?? "")}>
              {a.alert_rule}
            </td>
            <td>{fmtDecimal(toNum(a.total_premium), 0)}</td>
            <td>{fmtDecimal(toNum(a.volume_oi_ratio), 2)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
