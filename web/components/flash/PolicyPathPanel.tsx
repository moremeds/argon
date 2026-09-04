import { Panel } from "./Panel";
import type { PolicyPath } from "./view";
import styles from "./flash.module.css";

/**
 * The futures-implied policy path, with the run's own source line.
 *
 * THE SOURCE IS PRINTED VERBATIM. The recorded path is Frenzy futures-implied;
 * writing "CME FedWatch" over it would be argon attributing a number to a
 * vendor that never produced it — a data-integrity fault, not a copy choice.
 */
export function PolicyPathPanel({ path }: { path: PolicyPath }) {
  return (
    <Panel title="Policy path">
      <div
        className={styles.tape}
        style={{
          gridTemplateColumns: `repeat(${path.steps.length || 1}, minmax(0, 1fr))`,
        }}
      >
        {path.steps.map((step) => (
          <div key={step.date} className={styles.tile}>
            <span className={styles.lbl}>{step.date}</span>
            <span
              className={styles.mono}
              style={{ fontSize: 15, fontWeight: 700 }}
            >
              {step.implied}
            </span>
            {step.band ? (
              <span
                className={styles.mono}
                style={{ fontSize: 9.5, color: "var(--text-muted)" }}
              >
                {step.band}
              </span>
            ) : null}
            {step.call ? (
              <span
                className={styles.mono}
                style={{
                  fontSize: 10.5,
                  fontWeight: 700,
                  letterSpacing: "0.6px",
                  color:
                    step.call === "HIKE"
                      ? "var(--negative)"
                      : "var(--text-secondary)",
                }}
              >
                {step.call} {step.probability ?? ""}
              </span>
            ) : null}
          </div>
        ))}
      </div>
      <p
        style={{
          margin: "9px 0 0",
          fontSize: 11,
          lineHeight: 1.5,
          color: "var(--text-muted)",
        }}
      >
        {path.source}
      </p>
    </Panel>
  );
}
