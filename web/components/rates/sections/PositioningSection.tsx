import styles from "../RatesDesk.module.css";
import { statusLabel, toFiniteNumber } from "../format";
import type { Positioning } from "../types";

function fmtContracts(value: unknown): string {
  const n = toFiniteNumber(value, Number.NaN);
  if (!Number.isFinite(n)) return "n/a";
  return n.toLocaleString("en-US", { maximumFractionDigits: 0 });
}

function fmtPct(value: unknown): string {
  const n = toFiniteNumber(value, Number.NaN);
  if (!Number.isFinite(n)) return "n/a";
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(1)}% OI`;
}

export function PositioningSection({ positioning }: { positioning: Positioning }) {
  const rows = positioning.rows ?? [];
  const details = positioning.details ?? [];
  if (!rows.length && !details.length) {
    return (
      <div className={styles.notePanel}>
        <strong>{statusLabel(positioning.status)}</strong>
        <p>CFTC/TIC feeds not wired in Phase 1.</p>
      </div>
    );
  }
  return (
    <div className={styles.positioningStack}>
      <div className={styles.compactGrid}>
        {rows.map((row) => (
          <article className={styles.kpiTile} key={row.label}>
            <span>{row.label}</span>
            <strong>{fmtContracts(row.value)}</strong>
            <small>{row.unit}</small>
          </article>
        ))}
      </div>
      <div className={styles.positioningTableWrap}>
        <table className={styles.positioningTable}>
          <thead>
            <tr>
              <th>Contract</th>
              <th>Open interest</th>
              <th>Leveraged funds</th>
              <th>Asset managers</th>
              <th>Dealers</th>
            </tr>
          </thead>
          <tbody>
            {details.map((row) => (
              <tr key={`${row.contract_code}-${row.obs_date ?? ""}`}>
                <td>
                  <strong>{row.tenor_bucket}</strong>
                  <small>{row.contract_name}</small>
                </td>
                <td>{fmtContracts(row.open_interest)}</td>
                <td>
                  {fmtContracts(row.lev_money_net)}
                  <small>{fmtPct(row.lev_money_net_pct_oi)}</small>
                </td>
                <td>
                  {fmtContracts(row.asset_mgr_net)}
                  <small>{fmtPct(row.asset_mgr_net_pct_oi)}</small>
                </td>
                <td>
                  {fmtContracts(row.dealer_net)}
                  <small>{fmtPct(row.dealer_net_pct_oi)}</small>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className={styles.positioningRead}>
        {positioning.positioning_read ??
          "CFTC TFF Treasury futures positioning is unavailable."}
      </p>
    </div>
  );
}
