import { Panel } from "./Panel";
import type { Section } from "./view";
import styles from "./flash.module.css";

/** What the run considered and dropped, and why. */
export function RiskRegisterPanel({
  entries,
  tail,
}: {
  entries: Section[];
  tail?: string;
}) {
  return (
    <Panel title="Risk register" tail={tail}>
      <table>
        <thead>
          <tr>
            <th>Ticker</th>
            <th>Reason dropped</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((e, i) => (
            <tr key={`${e.title}-${i}`}>
              <td
                className={styles.mono}
                style={{ fontWeight: 700, verticalAlign: "top" }}
              >
                {e.title}
              </td>
              <td style={{ color: "var(--text-secondary)" }}>{e.body}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}
