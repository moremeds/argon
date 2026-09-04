import styles from "./flash.module.css";

/**
 * The reviewer's rows, in the reviewer's order.
 *
 * Every key the run filled, no key it did not, nothing reordered and nothing
 * added. This is the only part of a flash that says what to DO — a row
 * invented here is argon's opinion wearing the reviewer's name. The first row
 * renders larger because it IS the call; the rest are its terms.
 */
export function DecisionBlock({
  rows,
}: {
  rows: { label: string; value: string }[];
}) {
  return (
    <div className={styles.dec}>
      {rows.map((row, i) => (
        <div key={`${row.label}-${i}`} style={{ display: "contents" }}>
          <div className={styles.decKey} data-testid="decision-key">
            {row.label}
          </div>
          <div
            className={`${styles.decValue}${i === 0 ? ` ${styles.decCall}` : ""}`}
          >
            {row.value}
          </div>
        </div>
      ))}
    </div>
  );
}
