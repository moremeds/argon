import { Panel } from "./Panel";
import styles from "./flash.module.css";

/**
 * An absent section and an empty one are different claims.
 *
 * The panel is never omitted: "the run flagged nothing overnight" is a result,
 * and a missing panel would read as a run that never looked.
 */
export function OvernightPanel({ items }: { items: string[] }) {
  return (
    <Panel title="Overnight">
      {items.length === 0 ? (
        <p
          style={{
            margin: 0,
            fontSize: 12.5,
            lineHeight: 1.55,
            color: "var(--text-muted)",
          }}
        >
          Nothing was flagged overnight.
        </p>
      ) : (
        <div className={styles.stack}>
          {items.map((item, i) => (
            <p
              key={i}
              style={{
                margin: 0,
                fontSize: 12.5,
                lineHeight: 1.55,
                color: "var(--text-secondary)",
              }}
            >
              {item}
            </p>
          ))}
        </div>
      )}
    </Panel>
  );
}
