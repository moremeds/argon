import type { GexRow } from "./view";
import styles from "./flash.module.css";

const FIELDS = [
  ["spot", "Spot"],
  ["flip", "Gamma flip"],
  ["magnet", "Magnet"],
  ["callWall", "Call wall"],
  ["putWall", "Put wall"],
] as const;

function delta(before?: string, after?: string): string | null {
  if (before == null || after == null) return null;
  const a = Number.parseFloat(before);
  const b = Number.parseFloat(after);
  if (!Number.isFinite(a) || !Number.isFinite(b)) return null;
  const d = b - a;
  if (d === 0) return "0.00";
  return (d > 0 ? "+" : "−") + Math.abs(d).toFixed(2);
}

/**
 * What moved between two runs of the same day.
 *
 * Rendered ONLY when both runs are in hand — the caller decides that. A delta
 * against a missing side is not a small delta, it is no delta, and drawing it
 * as "0.00" would be argon asserting the level held.
 */
export function GexDeltaTable({
  before,
  after,
}: {
  before: GexRow[];
  after: GexRow[];
}) {
  const byTicker = new Map(before.map((r) => [r.ticker, r]));
  return (
    <div className={styles.scrollx}>
      <table>
        <thead>
          <tr>
            <th>Ticker</th>
            <th>Level</th>
            <th className="n">Intraday</th>
            <th className="n">Close</th>
            <th className="n">Δ</th>
          </tr>
        </thead>
        <tbody>
          {after.flatMap((row) => {
            const prior = byTicker.get(row.ticker);
            if (!prior) return [];
            return FIELDS.map(([key, label], i) => {
              const d = delta(prior[key], row[key]);
              const tone =
                d == null || d === "0.00"
                  ? "var(--text-muted)"
                  : d.startsWith("−")
                    ? "var(--negative)"
                    : "var(--positive)";
              return (
                <tr key={`${row.ticker}-${key}`}>
                  <td className={styles.mono} style={{ fontWeight: 700 }}>
                    {i === 0 ? row.ticker : ""}
                  </td>
                  <td style={{ fontSize: 11.5, color: "var(--text-muted)" }}>
                    {label}
                  </td>
                  <td className="n" style={{ color: "var(--text-muted)" }}>
                    {prior[key] ?? "—"}
                  </td>
                  <td className="n">
                    <span style={{ color: "var(--text-muted)" }}>→ </span>
                    {row[key] ?? "—"}
                  </td>
                  <td className="n" style={{ color: tone }}>
                    {d ?? "—"}
                  </td>
                </tr>
              );
            });
          })}
        </tbody>
      </table>
    </div>
  );
}
