import styles from "../RatesDesk.module.css";
import { fmtValue, statusLabel, toFiniteNumber } from "../format";
import type { SummaryTile, Supply } from "../types";

function fmtAuctionSize(value: unknown): string {
  const n = toFiniteNumber(value, Number.NaN);
  if (!Number.isFinite(n)) return "n/a";
  return `$${n.toFixed(1)}bn`;
}

function fmtSupplyMetric(tile: SummaryTile): string {
  const n = toFiniteNumber(tile.value, Number.NaN);
  if (!Number.isFinite(n)) return "n/a";
  if (tile.unit === "$T") return `$${n.toFixed(2)}T`;
  if (tile.unit === "$bn") return `$${n.toFixed(1)}bn`;
  if (tile.unit === "%") return `${n.toFixed(1)}%`;
  if (tile.unit === "x") return `${n.toFixed(2)}x`;
  return fmtValue(tile.value, tile.unit, 2);
}

function fmtPercent(value: unknown): string {
  const n = toFiniteNumber(value, Number.NaN);
  if (!Number.isFinite(n)) return "n/a";
  return `${n.toFixed(1)}%`;
}

export function SupplySection({ supply }: { supply: Supply | undefined }) {
  const recentAuctions = supply?.recent_auctions ?? [];
  const fiscal = supply?.fiscal ?? [];
  if (!recentAuctions.length && !fiscal.length) {
    return (
      <div className={styles.notePanel}>
        <strong>{statusLabel(supply?.status)}</strong>
        {(supply?.notes?.length
          ? supply.notes
          : ["Treasury auction and FiscalData supply feeds are unavailable."]
        ).map((note) => (
          <p key={note}>{note}</p>
        ))}
      </div>
    );
  }

  return (
    <div className={styles.supplyGrid}>
      <article className={styles.supplyCard}>
        <div className={styles.policyCardTop}>
          <h3>Recent auctions</h3>
          <span>TreasuryDirect</span>
        </div>
        <div className={styles.supplyTableWrap}>
          <table className={styles.supplyTable}>
            <thead>
              <tr>
                <th>Issue</th>
                <th>Size</th>
                <th>High rate</th>
                <th>Bid cover</th>
                <th>Indirect</th>
              </tr>
            </thead>
            <tbody>
              {recentAuctions.map((row) => (
                <tr key={`${row.cusip}-${row.auction_date}`}>
                  <td>
                    <strong>
                      {row.security_term} {row.security_type}
                    </strong>
                    <small>{row.auction_date}</small>
                  </td>
                  <td>{fmtAuctionSize(row.offering_amount)}</td>
                  <td>{fmtValue(row.high_rate, "%", 3)}</td>
                  <td>{fmtValue(row.bid_to_cover, "", 2)}</td>
                  <td>{fmtPercent(row.indirect_bidder_pct)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {supply?.supply_read ? (
          <p className={styles.positioningRead}>{supply.supply_read}</p>
        ) : null}
      </article>

      <article className={styles.supplyCard}>
        <div className={styles.policyCardTop}>
          <h3>Issuance & fiscal</h3>
          <span>FiscalData + FRED</span>
        </div>
        <div className={styles.supplyMetricGrid}>
          {fiscal.map((tile) => (
            <article className={styles.kpiTile} key={tile.label}>
              <span>{tile.label}</span>
              <strong>{fmtSupplyMetric(tile)}</strong>
              <small>{statusLabel(tile.status)}</small>
            </article>
          ))}
          {(supply?.auctions ?? []).map((tile) => (
            <article className={styles.kpiTile} key={tile.label}>
              <span>{tile.label}</span>
              <strong>{fmtSupplyMetric(tile)}</strong>
              <small>{statusLabel(tile.status)}</small>
            </article>
          ))}
        </div>
      </article>
    </div>
  );
}
