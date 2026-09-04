import type { TapeItem } from "./view";
import { Tile } from "./Tile";
import styles from "./flash.module.css";

/**
 * The uniform tile row, at most 7 wide and balanced: 8 items go 4+4, not 7+1.
 * A ragged last row reads as a missing tile.
 */
function columns(count: number): number {
  if (count === 0) return 1;
  return Math.ceil(count / Math.ceil(count / 7));
}

export function TapeStrip({
  items,
  sourceLine,
}: {
  items: TapeItem[];
  sourceLine?: string;
}) {
  // No tape is not an empty tape: render nothing rather than an empty grid
  // that reads as tiles that failed to load.
  if (items.length === 0) return null;
  return (
    <div>
      <div
        className={styles.tape}
        style={{
          gridTemplateColumns: `repeat(${columns(items.length)}, minmax(0, 1fr))`,
        }}
      >
        {items.map((item) => (
          <div key={item.label} data-testid="flash-tile">
            <Tile
              label={item.label}
              value={item.value}
              change={item.change}
              source={item.source}
            />
          </div>
        ))}
      </div>
      {sourceLine ? <p className={styles.tapesrc}>{sourceLine}</p> : null}
    </div>
  );
}
