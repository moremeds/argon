import styles from "./flash.module.css";

/** `+12bp` → pos, `-10.87` → neg, nothing → none. Read off the STRING the */
/*  tenant wrote; argon never re-derives a sign it was not given. */
function signOf(change: string): "pos" | "neg" {
  return /^[-−]/.test(change) ? "neg" : "pos";
}

/**
 * One price tile: label, value, change. The same shape in every phase.
 *
 * THE CHANGE SLOT IS ALWAYS RENDERED. A tile whose source carried no change
 * gets an em dash, not a blank and never a number borrowed from another phase
 * — an intraday tile silently wearing the premarket change is the one lie this
 * page could tell that a reader has no way to catch.
 *
 * Provenance goes on `title` and into the sources line under the row. It never
 * enters the layout: seven tiles with seven different-length source lines stop
 * being a tape.
 */
export function Tile({
  label,
  value,
  change,
  source,
}: {
  label: string;
  value: string;
  change?: string | null;
  source?: string;
}) {
  const recorded = change != null && change !== "";
  return (
    <div
      className={styles.tile}
      data-testid={`flash-tile-${label}`}
      title={source || undefined}
    >
      <span className={styles.lbl}>{label}</span>
      <span className={styles.tileValue}>{value}</span>
      {recorded ? (
        <span className={styles.chg} data-sign={signOf(change)}>
          {change.replace(/^-/, "−")}
        </span>
      ) : (
        <span
          className={styles.chg}
          data-sign="none"
          aria-label="no change recorded"
        >
          —
        </span>
      )}
    </div>
  );
}
