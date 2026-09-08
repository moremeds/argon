import type { FocusBlock } from "./view";

import { Panel } from "./Panel";
import styles from "./flash.module.css";

/**
 * The names under watch, in the run's own order.
 *
 * Rank is the row's position — helium ranked the list when it wrote it, and
 * re-sorting here would silently disagree with the numbered list the same run
 * printed in prose. An IV rank is 0–100 as computed; a missing one is an em
 * dash, never a zero. `sticky` marks a name carried over rather than picked
 * fresh, and the open-call id is printed verbatim because it is the key that
 * ties this row to the call it continues.
 */
export function FocusPanel({ focus }: { focus: FocusBlock }) {
  const rows = focus.rows ?? [];
  const period = focus.period === "weekly" ? "this week" : "today";
  return (
    <Panel title="Focus" tail={`${rows.length} names · ${period}`}>
      <div className={styles.scrollx}>
        <table>
          <thead>
            <tr>
              <th className="n">#</th>
              <th>Ticker</th>
              <th>Event</th>
              <th className="n">IV rank</th>
              <th>Open call</th>
              <th>Why</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={`${r.ticker}-${i}`}>
                <td className="n" style={{ color: "var(--text-muted)" }}>
                  {i + 1}
                </td>
                <td className={styles.mono} style={{ fontWeight: 700 }}>
                  {r.ticker}
                  {r.sticky ? (
                    <span
                      className={styles.sticky}
                      title="carried over from the previous run"
                    >
                      ●
                    </span>
                  ) : null}
                </td>
                <td className={styles.sans}>{r.event || "—"}</td>
                <td className="n">
                  {typeof r.ivRank === "number" ? r.ivRank.toFixed(0) : "—"}
                </td>
                <td
                  className={styles.mono}
                  style={{ fontSize: 10.5, color: "var(--text-muted)" }}
                >
                  {r.openCall ?? "—"}
                </td>
                <td className={styles.sans}>{r.why || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className={styles.note}>
        {typeof focus.churn === "number"
          ? `churn ${focus.churn}`
          : "churn not recorded"}
        {focus.shortfall ? ` · ${focus.shortfall}` : ""}
        {rows.some((r) => r.sticky) ? " · ● carried over" : ""}
      </div>
    </Panel>
  );
}
