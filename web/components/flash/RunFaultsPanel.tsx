import { Panel } from "./Panel";
import styles from "./flash.module.css";

/**
 * The run's id and what it could not do.
 *
 * A run that degraded and said so is a different object from a run that
 * succeeded, and the id is what makes the difference checkable against helium.
 */
export function RunFaultsPanel({
  runId,
  faults,
}: {
  runId?: string;
  faults: string[];
}) {
  return (
    <Panel title="Run health" tail="faults this run">
      {runId ? (
        <span
          className={styles.mono}
          style={{
            fontSize: 11,
            color: "var(--text-muted)",
            wordBreak: "break-all",
            display: "block",
            marginBottom: 8,
          }}
        >
          {runId}
        </span>
      ) : null}
      {faults.length === 0 ? (
        <p style={{ margin: 0, fontSize: 11.5, color: "var(--text-muted)" }}>
          No faults recorded.
        </p>
      ) : (
        <ul
          style={{
            margin: 0,
            paddingLeft: 16,
            color: "var(--text-muted)",
            fontSize: 11.5,
            lineHeight: 1.7,
          }}
        >
          {faults.map((f, i) => (
            <li key={i}>{f}</li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
