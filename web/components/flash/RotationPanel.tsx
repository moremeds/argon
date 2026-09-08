import type { Rotation, RotationRow } from "./view";

import { Panel } from "./Panel";
import styles from "./flash.module.css";

/** One percentage as helium measured it. `null` is untested, never zero. */
function pct(v: number | null | undefined): string {
  if (typeof v !== "number" || !Number.isFinite(v)) return "untested";
  return `${v > 0 ? "+" : ""}${v.toFixed(1)}`;
}

function cell(v: number | null | undefined) {
  const missing = typeof v !== "number" || !Number.isFinite(v);
  return (
    <td
      className="n"
      style={{
        color: missing
          ? "var(--text-muted)"
          : v! > 0
            ? "var(--positive)"
            : v! < 0
              ? "var(--negative)"
              : "var(--text-secondary)",
        fontStyle: missing ? "italic" : undefined,
      }}
    >
      {pct(v)}
    </td>
  );
}

/**
 * What led and what lagged, and by how much against the benchmark.
 *
 * A symbol whose bars did not arrive prints "untested" in every cell and
 * carries the run's reason underneath — the one thing a rotation table must
 * never do is let a missing week read as a flat week.
 */
export function RotationPanel({ rotation }: { rotation: Rotation }) {
  const rows: RotationRow[] = rotation.rows ?? [];
  const stale = rows.filter((r) => r.untested);
  const tail = [
    rotation.benchmark ? `vs ${rotation.benchmark}` : null,
    rotation.asOf ? `as of ${rotation.asOf}` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <Panel title="Rotation" tail={tail || undefined}>
      <div className={styles.scrollx}>
        <table>
          <thead>
            <tr>
              <th>Symbol</th>
              <th className="n">1w</th>
              <th className="n">4w</th>
              <th className="n">12w</th>
              <th className="n">1w excess</th>
              <th className="n">4w excess</th>
              <th className="n">12w excess</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={`${r.symbol}-${i}`}>
                <td className={styles.mono} style={{ fontWeight: 700 }}>
                  {r.label || r.symbol}
                </td>
                {cell(r.w1)}
                {cell(r.w4)}
                {cell(r.w12)}
                {cell(r.excess1w)}
                {cell(r.excess4w)}
                {cell(r.excess12w)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {stale.length > 0 ? (
        <div className={styles.note}>
          {stale
            .map((r) => `${r.label || r.symbol}: ${r.untested}`)
            .join(" · ")}
        </div>
      ) : null}
    </Panel>
  );
}
