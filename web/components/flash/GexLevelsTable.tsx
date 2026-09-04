import type { GexRow } from "./view";
import styles from "./flash.module.css";

/** Dealer gamma levels as the run recorded them — strings, not re-formatted. */
export function GexLevelsTable({ rows }: { rows: GexRow[] }) {
  return (
    <div className={styles.scrollx}>
      <table>
        <thead>
          <tr>
            <th>Ticker</th>
            <th className="n">Spot</th>
            <th className="n">Flip</th>
            <th className="n">Magnet</th>
            <th className="n">Call wall</th>
            <th className="n">Put wall</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.ticker}>
              <td className={styles.mono} style={{ fontWeight: 700 }}>
                {r.ticker}
              </td>
              <td className="n">{r.spot ?? "—"}</td>
              <td className="n">{r.flip ?? "—"}</td>
              <td className="n">{r.magnet ?? "—"}</td>
              <td className="n" style={{ color: "var(--positive)" }}>
                {r.callWall ?? "—"}
              </td>
              <td className="n" style={{ color: "var(--negative)" }}>
                {r.putWall ?? "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
