import { Panel } from "./Panel";
import type { ScheduleItem } from "./view";
import styles from "./flash.module.css";

/** Time / event / consensus-prior. A row with no consensus gets an em dash. */
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
              <td style={{ color: "var(--text-secondary)" }}>{item.event}</td>
              <td
                className="n"
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
