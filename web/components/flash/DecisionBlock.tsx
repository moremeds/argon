import { Fragment } from "react";

import styles from "./flash.module.css";

/**
 * "WhyNow" is the reviewer's key, not the reader's word.
 *
 * The camelCase is the transport's, so it is split for display and only the
 * first word is capitalised — the label is presentation, and rewriting it does
 * not touch the value, which stays exactly as the run recorded it.
 */
export function humanizeKey(key: string): string {
  const words = key
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/([A-Z]+)([A-Z][a-z])/g, "$1 $2")
    .trim()
    .split(/\s+/)
    .filter((w) => w.length > 0);
  if (words.length === 0) return key;
  return words.map((w, i) => (i === 0 ? w : w.toLowerCase())).join(" ");
}

/**
 * The reviewer's rows, in the reviewer's order.
 *
 * Every key the run filled, no key it did not, nothing reordered and nothing
 * added. This is the only part of a flash that says what to DO — a row
 * invented here is argon's opinion wearing the reviewer's name. The first row
 * renders larger because it IS the call; the rest are its terms.
 *
 * Key and value are DIRECT children of the grid. A wrapper element, even a
 * `display: contents` one, takes the `.dec > div` cell rules for itself and
 * leaves the real cells with no padding, no border and no column.
 */
export function DecisionBlock({
  rows,
}: {
  rows: { label: string; value: string }[];
}) {
  return (
    <div className={styles.dec}>
      {rows.map((row, i) => (
        <Fragment key={`${row.label}-${i}`}>
          <div
            className={`${styles.lbl} ${styles.decKey}`}
            data-testid="decision-key"
          >
            {humanizeKey(row.label)}
          </div>
          <div
            className={`${styles.decValue}${i === 0 ? ` ${styles.decCall}` : ""}`}
          >
            {row.value}
          </div>
        </Fragment>
      ))}
    </div>
  );
}
