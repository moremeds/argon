import { Panel } from "./Panel";
import type { ScheduleItem } from "./view";
import styles from "./flash.module.css";

/**
 * Time / event / consensus-prior. A row with no consensus gets an em dash.
 *
 * TIME and CONS/PRIOR are compared down their column, so they are monospaced;
 * the event NAME is a phrase and is set in the body sans. Both are stated
 * here rather than inherited: `app/globals.css` makes every `td` monospaced
 * for the desk's numeric tables, and a table carrying words needs to say so.
 */
export function SchedulePanel({ items }: { items: ScheduleItem[] }) {
  return (
    <Panel title="Today's schedule">
      <table>
        <thead>
          <tr>
            <th>Time</th>
            <th>Event</th>
            <th className="n">Cons / prior</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item, i) => (
            <tr key={`${item.time}-${item.event}-${i}`}>
              <td className={styles.mono} style={{ whiteSpace: "nowrap" }}>
                {item.group ? (
                  <span className={styles.lbl} style={{ display: "block" }}>
                    {item.group}
                  </span>
                ) : null}
                {item.time}
              </td>
              <td
                className={styles.sans}
                style={{ color: "var(--text-secondary)" }}
              >
                {item.event}
              </td>
              <td
                className={`n ${styles.mono}`}
                style={{
                  whiteSpace: "nowrap",
                  color: "var(--text-secondary)",
                }}
              >
                {item.consensus || "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}
