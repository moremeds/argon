import { Panel } from "./Panel";
import type { Section } from "./view";
import styles from "./flash.module.css";

/**
 * What the run considered and dropped, and why.
 *
 * The ticker is a ticker and stays monospaced; the reason is a sentence and is
 * set in the body sans, against the global `td` monospace default.
 */
export function RiskRegisterPanel({
  entries,
  tail,
}: {
  entries: Section[];
  tail?: string;
}) {
  return (
    <Panel title="Passed over" tail={tail}>
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
              <td
                className={styles.sans}
                style={{ color: "var(--text-secondary)" }}
              >
                {e.body}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}
