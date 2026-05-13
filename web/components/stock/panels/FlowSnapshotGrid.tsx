import type { components } from "@/lib/types";
import { fmtDecimal, fmtSigned, toNum } from "@/lib/formatters";
import { SNAPSHOT_TOOLTIPS, type TooltipCopy } from "./snapshotTooltips";

type Report = components["schemas"]["SingleStockReport"];
type ShortData = NonNullable<Report["short_data"]>;

type Props = {
  flow: Report["flow"];
  darkPool: { prints: number; notional: Report["dark_pool_notional"] };
  shortData: ShortData | null;
};

export function FlowSnapshotGrid({ flow, darkPool, shortData }: Props) {
  return (
    <div
      role="region"
      aria-label="Flow snapshot"
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
        gap: 12,
        padding: 16,
        background: "var(--bg-panel)",
        border: "1px solid var(--border-dim)",
      }}
    >
      <Tile
        label="ALERTS"
        tip="alerts"
        value={fmtDecimal(flow.flow_count, 0)}
      />
      <Tile
        label="NET PREMIUM"
        tip="netPremium"
        value={fmtSigned(toNum(flow.net_premium), 0)}
      />
      <Tile
        label="BULL PREMIUM"
        tip="bullPremium"
        value={fmtDecimal(toNum(flow.bull_premium), 0)}
      />

      <Tile
        label="BEAR PREMIUM"
        tip="bearPremium"
        value={fmtDecimal(toNum(flow.bear_premium), 0)}
      />
      <Tile
        label="ASK PREMIUM"
        tip="askPremium"
        value={fmtDecimal(toNum(flow.ask_side_premium), 0)}
      />
      <Tile
        label="BID PREMIUM"
        tip="bidPremium"
        value={fmtDecimal(toNum(flow.bid_side_premium), 0)}
      />

      <Tile
        label="DARK POOL PRINTS"
        tip="darkPoolPrints"
        value={fmtDecimal(darkPool.prints, 0)}
      />
      <Tile
        label="DARK POOL NOTIONAL"
        tip="darkPoolNotional"
        value={fmtDecimal(toNum(darkPool.notional), 0)}
      />
      <div />

      <Tile
        label="SHARES AVAIL"
        tip="sharesAvail"
        value={fmtDecimal(shortData?.short_shares_available ?? null, 0)}
      />
      <Tile
        label="FEE RATE"
        tip="feeRate"
        value={fmtDecimal(toNum(shortData?.fee_rate ?? null), 4)}
      />
      <Tile
        label="REBATE RATE"
        tip="rebateRate"
        value={fmtDecimal(toNum(shortData?.rebate_rate ?? null), 4)}
      />
    </div>
  );
}

function Tile({
  label,
  tip,
  value,
}: {
  label: string;
  tip: keyof typeof SNAPSHOT_TOOLTIPS;
  value: string;
}) {
  const t: TooltipCopy = SNAPSHOT_TOOLTIPS[tip];
  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 10,
            letterSpacing: 1.5,
            color: "var(--text-muted)",
            textTransform: "uppercase",
          }}
        >
          {label}
        </span>
        <details style={{ display: "inline-block", position: "relative" }}>
          <summary
            aria-label={`${label} explanation`}
            style={{
              listStyle: "none",
              cursor: "help",
              fontSize: 10,
              color: "var(--text-muted)",
              border: "1px solid var(--border-dim)",
              borderRadius: "50%",
              width: 12,
              height: 12,
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            i
          </summary>
          <div
            style={{
              position: "absolute",
              zIndex: 10,
              background: "var(--bg-panel)",
              border: "1px solid var(--border-dim)",
              padding: 8,
              maxWidth: 280,
              fontSize: 11,
              color: "var(--text-primary)",
            }}
          >
            <p style={{ margin: 0 }}>{t.definition}</p>
            <p style={{ margin: "4px 0 0 0", color: "var(--text-secondary)" }}>
              {t.benchmark}
            </p>
          </div>
        </details>
      </div>
      <div
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 22,
          fontWeight: 700,
          color: "var(--text-primary)",
        }}
      >
        {value}
      </div>
    </div>
  );
}
