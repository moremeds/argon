import { Panel } from "./Panel";
import styles from "./flash.module.css";

/**
 * What the run saw and deliberately did not build the argument on.
 *
 * It sits BELOW the claim for that reason: printing it first would make the
 * leftovers compete with the one thing the run actually decided.
 */
export function EverythingElsePanel({ items }: { items: string[] }) {
  return (
    <Panel title="Everything else" tail={`${items.length} not the argument`}>
      <ul className={styles.bodyList}>
        {items.map((item, i) => (
          <li key={i}>{item}</li>
        ))}
      </ul>
    </Panel>
  );
}
