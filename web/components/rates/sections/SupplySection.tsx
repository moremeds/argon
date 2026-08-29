import styles from "../RatesDesk.module.css";
import { BoardRead, BoardRefusal } from "@/components/macro/domain/BoardPanel";
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

/** Shared empty state. Both halves went missing together before they were split, and
 *  they still do: one `supply` publisher feeds them, so a feed outage is one message. */
function SupplyUnavailable({ supply }: { supply: Supply | undefined }) {
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

/**
 * Board t2 — "Auction demand · did anyone show up".
 *
 * Split from the issuance metrics on 2026-08-29. The board keeps them apart because they
 * answer different questions: issuance is how much paper the Treasury is bringing, and
 * this is whether anyone turned up to absorb it. Under one "Supply" heading a strong
 * bid-to-cover and a heavy calendar read as one fact about supply, and they are two
 * facts that frequently point opposite ways.
 */
export function AuctionDemandSection({
  supply,
}: {
  supply: Supply | undefined;
}) {
  const recentAuctions = supply?.recent_auctions ?? [];
  if (!recentAuctions.length) return <SupplyUnavailable supply={supply} />;
  const strongestIndirect = recentAuctions.reduce((best, row) =>
    toFiniteNumber(row.indirect_bidder_pct, -Infinity) >
    toFiniteNumber(best.indirect_bidder_pct, -Infinity)
      ? row
      : best,
  );

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
        <BoardRead>
          Highest indirect participation: {" "}
          <b>{fmtPercent(strongestIndirect.indirect_bidder_pct)}</b> on the{" "}
          {strongestIndirect.security_term} {strongestIndirect.security_type}.
        </BoardRead>
        <BoardRefusal>
          Auction high rates are printed with each security type; nominal and
          inflation-protected securities are not compared as though their rates
          were on the same basis.
        </BoardRefusal>
      </article>
    </div>
  );
}

/**
 * The issuance and fiscal readings that stand under the supply SUB-STATE verdict.
 *
 * Rendered inside the sub-state panel rather than as a panel of its own: the board gives
 * tab 02 a `Supply SUB-STATE` panel and an `Auction demand` panel, and these tiles are
 * what the first one's verdict is computed from.
 */
export function SupplyFiscalSection({
  supply,
}: {
  supply: Supply | undefined;
}) {
  const fiscal = supply?.fiscal ?? [];
  const auctions = supply?.auctions ?? [];
  if (!fiscal.length && !auctions.length)
    return <SupplyUnavailable supply={supply} />;

  return (
    <div className={styles.supplyGrid}>
      <article className={styles.supplyCard}>
        <div className={styles.policyCardTop}>
          <h3>Issuance &amp; fiscal</h3>
          <span>FiscalData + FRED</span>
        </div>
        <div className="big">
          {[...fiscal, ...auctions].filter((tile) => tile.status !== "ok").length}
          <small> of {fiscal.length + auctions.length} supply readings unavailable</small>
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
        {supply?.supply_read ? (
          <BoardRead>{supply.supply_read}</BoardRead>
        ) : null}
      </article>
    </div>
  );
}
