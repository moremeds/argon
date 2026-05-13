"use client";

import { useState } from "react";
import type { components } from "@/lib/types";
import { fmtDecimal, fmtMoney, toNum } from "@/lib/formatters";
import { SNAPSHOT_TOOLTIPS, type TooltipCopy } from "./snapshotTooltips";

// UW caps share-availability inventory at 10M. Anything at that exact value
// is "easy borrow, true count unknown" — surface as 10M+ rather than a
// misleadingly precise number.
const SHARES_AVAIL_CAP = 10_000_000;
function fmtSharesAvail(v: number | null | undefined): string {
  if (v == null) return "—";
  if (v >= SHARES_AVAIL_CAP) return "10M+";
  return fmtDecimal(v, 0);
}

const SECTION_HEADING: React.CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: 12,
  letterSpacing: 1.5,
  textTransform: "uppercase",
  color: "var(--text-muted)",
  margin: "0 0 8px 0",
};

type Report = components["schemas"]["SingleStockReport"];
type ShortData = NonNullable<Report["short_data"]>;

type Props = {
  flow: Report["flow"];
  darkPool: { prints: number; notional: Report["dark_pool_notional"] };
  shortData: ShortData | null;
};

const tileStyle: React.CSSProperties = {
  background: "var(--bg-panel)",
  border: "1px solid var(--border-dim)",
  borderRadius: 4,
  padding: "12px 14px",
  display: "flex",
  flexDirection: "column",
  gap: 6,
  minWidth: 0,
};

const labelStyle: React.CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: 10,
  letterSpacing: 1.5,
  textTransform: "uppercase",
  color: "var(--text-muted)",
};

const valueStyle: React.CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontWeight: 700,
  fontSize: 22,
  color: "var(--text-primary)",
  lineHeight: 1,
};

function netPremiumColor(v: number | null): string {
  if (v == null) return "var(--text-primary)";
  if (v > 0) return "var(--positive)";
  if (v < 0) return "var(--negative)";
  return "var(--text-primary)";
}

export function FlowSnapshotGrid({ flow, darkPool, shortData }: Props) {
  const netPrem = toNum(flow.net_premium);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <section>
        <h3 style={SECTION_HEADING}>Options Flow</h3>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(6, minmax(0, 1fr))",
            gap: 12,
          }}
        >
          <Tile
            label="Alerts"
            tip="alerts"
            value={fmtDecimal(flow.flow_count, 0)}
          />
          <Tile
            label="Net Premium"
            tip="netPremium"
            value={fmtMoney(netPrem, { signed: true })}
            valueColor={netPremiumColor(netPrem)}
          />
          <Tile
            label="Bull Premium"
            tip="bullPremium"
            value={fmtMoney(toNum(flow.bull_premium))}
            valueColor="var(--positive)"
          />
          <Tile
            label="Bear Premium"
            tip="bearPremium"
            value={fmtMoney(toNum(flow.bear_premium))}
            valueColor="var(--negative)"
          />
          <Tile
            label="Ask Premium"
            tip="askPremium"
            value={fmtMoney(toNum(flow.ask_side_premium))}
          />
          <Tile
            label="Bid Premium"
            tip="bidPremium"
            value={fmtMoney(toNum(flow.bid_side_premium))}
          />
        </div>
      </section>

      <section>
        <h3 style={SECTION_HEADING}>Dark Pool & Short Interest</h3>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(5, minmax(0, 1fr))",
            gap: 12,
          }}
        >
          <Tile
            label="DP Prints"
            tip="darkPoolPrints"
            value={fmtDecimal(darkPool.prints, 0)}
          />
          <Tile
            label="DP Notional"
            tip="darkPoolNotional"
            value={fmtMoney(toNum(darkPool.notional))}
          />
          <Tile
            label="Shares Avail"
            tip="sharesAvail"
            value={fmtSharesAvail(shortData?.short_shares_available ?? null)}
          />
          <Tile
            label="Fee Rate"
            tip="feeRate"
            value={fmtDecimal(toNum(shortData?.fee_rate ?? null), 4)}
          />
          <Tile
            label="Rebate Rate"
            tip="rebateRate"
            value={fmtDecimal(toNum(shortData?.rebate_rate ?? null), 4)}
          />
        </div>
      </section>
    </div>
  );
}

function Tile({
  label,
  tip,
  value,
  valueColor,
}: {
  label: string;
  tip: keyof typeof SNAPSHOT_TOOLTIPS;
  value: string;
  valueColor?: string;
}) {
  const t: TooltipCopy = SNAPSHOT_TOOLTIPS[tip];
  const [open, setOpen] = useState(false);
  return (
    <div style={tileStyle}>
      <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
        <span style={labelStyle}>{label}</span>
        <span
          onMouseEnter={() => setOpen(true)}
          onMouseLeave={() => setOpen(false)}
          style={{ display: "inline-block", position: "relative" }}
        >
          <span
            aria-label={`${label} explanation`}
            style={{
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
          </span>
          {open && (
            <div
              style={{
                position: "absolute",
                top: 18,
                left: 0,
                zIndex: 10,
                background: "var(--bg-panel)",
                border: "1px solid var(--border-dim)",
                padding: 8,
                width: 360,
                fontSize: 11,
                lineHeight: 1.4,
                color: "var(--text-primary)",
              }}
            >
              <p style={{ margin: 0 }}>{t.definition}</p>
              <p
                style={{ margin: "4px 0 0 0", color: "var(--text-secondary)" }}
              >
                {t.benchmark}
              </p>
            </div>
          )}
        </span>
      </div>
      <div style={{ ...valueStyle, color: valueColor ?? valueStyle.color }}>
        {value}
      </div>
    </div>
  );
}
