import type { components } from "@/lib/types";
import {
  fmtDecimal,
  fmtRelativeAgo,
  fmtTimeOfDay,
  toNum,
} from "@/lib/formatters";
import { describeAlertRule, UW_ALERT_RULES } from "@/lib/uw-alert-rules";

type Alert = components["schemas"]["FlowAlert"];

type AlertWithMover = Alert & {
  oiDiff?: number | null;
};

function flagsFor(a: Alert): string {
  const f: string[] = [];
  if (a.has_sweep) f.push("SWEEP");
  if (a.has_floor) f.push("FLOOR");
  if (a.has_multileg) f.push("MULTI");
  if (a.all_opening_trades) f.push("OPEN");
  return f.join(" · ");
}

function fmtStrike(s: string | null | undefined): string {
  const n = toNum(s);
  return n == null ? "—" : `$${n.toFixed(2)}`;
}

function typeColor(t: string | null | undefined): string {
  if (t === "C" || t === "call") return "var(--positive)";
  if (t === "P" || t === "put") return "var(--negative)";
  return "var(--text-primary)";
}

export function TopAlertsTable({
  alerts,
  oiMoverIndex,
  now = new Date(),
}: {
  alerts: Alert[];
  // option_symbol → oi_diff_plain, used to render the cross-ref ΔOI badge
  oiMoverIndex?: Map<string, number>;
  // Injectable for tests; defaults to render-time wall clock.
  now?: Date;
}) {
  const rows: AlertWithMover[] = [...alerts]
    .sort(
      (a, b) => (toNum(b.total_premium) ?? 0) - (toNum(a.total_premium) ?? 0),
    )
    .slice(0, 10)
    .map((a) => ({
      ...a,
      oiDiff: a.option_chain ? oiMoverIndex?.get(a.option_chain) : null,
    }));

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
          <th title="Tape time when this alert fired (your local timezone).">
            TIME
          </th>
          <th>TYPE</th>
          <th>EXPIRY</th>
          <th>STRIKE</th>
          <th>PREMIUM</th>
          <th>SIZE</th>
          <th>VOL</th>
          <th>OI</th>
          <th title="Volume divided by Open Interest — &gt;1 means today's flow exceeds existing positioning.">
            VOL÷OI
          </th>
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
          <th>FLAGS</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((a) => (
          <tr key={a.id} style={{ borderTop: "1px solid var(--border-dim)" }}>
            <td
              title={a.created_at ?? undefined}
              style={{ whiteSpace: "nowrap" }}
            >
              <span style={{ color: "var(--text-primary)" }}>
                {fmtTimeOfDay(a.created_at)}
              </span>
              {a.created_at && (
                <span
                  style={{
                    marginLeft: 6,
                    color: "var(--text-muted)",
                    fontSize: 10,
                  }}
                >
                  · {fmtRelativeAgo(a.created_at, now)}
                </span>
              )}
            </td>
            <td style={{ color: typeColor(a.type) }}>{a.type ?? "—"}</td>
            <td>{a.expiry ?? "—"}</td>
            <td>{fmtStrike(a.strike)}</td>
            <td>{fmtDecimal(toNum(a.total_premium), 0)}</td>
            <td>{fmtDecimal(a.total_size, 0)}</td>
            <td>
              {fmtDecimal(a.volume, 0)}
              {a.oiDiff != null && a.oiDiff !== 0 && (
                <span
                  title="This contract is also a top OI mover"
                  style={{
                    marginLeft: 6,
                    fontSize: 10,
                    color: a.oiDiff > 0 ? "var(--positive)" : "var(--negative)",
                  }}
                >
                  ΔOI {a.oiDiff > 0 ? "+" : ""}
                  {fmtDecimal(a.oiDiff, 0)}
                </span>
              )}
            </td>
            <td>{fmtDecimal(a.open_interest, 0)}</td>
            <td>{fmtDecimal(toNum(a.volume_oi_ratio), 2)}</td>
            <td title={describeAlertRule(a.alert_rule ?? "")}>
              {a.alert_rule}
            </td>
            <td style={{ color: "var(--text-muted)" }}>{flagsFor(a)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
