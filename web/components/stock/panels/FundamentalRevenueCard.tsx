import type { components } from "@/lib/types";
import { FundamentalBackPlaceholder } from "./FundamentalBackPlaceholder";
import { FundamentalCardBack } from "./FundamentalCardBack";
import { FundamentalSparkline } from "./FundamentalSparkline";
import {
  backPanelStyle,
  labelStyle,
  tileButtonStyle,
} from "./fundamentalShared";

type Detail = components["schemas"]["FundamentalFeatureDetail"];

/** 253491000000 -> "$253.5B". Nulls render as an em dash, never as $0. */
export function fmtCompactUsd(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  const abs = Math.abs(v);
  if (abs >= 1e12) return `$${(v / 1e12).toFixed(1)}T`;
  if (abs >= 1e9) return `$${(v / 1e9).toFixed(1)}B`;
  if (abs >= 1e6) return `$${(v / 1e6).toFixed(1)}M`;
  return `$${v.toFixed(0)}`;
}

/**
 * The eighth card: TTM revenue, net income and free cash flow.
 *
 * Descriptive, and it must LOOK descriptive. The seven tiles beside it are
 * members of a validated set; this one enters no composite, so it carries no
 * percentile chip and its footer says `descriptive · not scored` where a
 * subscore tile states a direction. A tile that looked identical would be read
 * as an eighth measured feature, and the composite's verdicts do not cover it.
 *
 * It also balances the grid to 8, which is what prompted it.
 */
export function FundamentalRevenueCard({
  detail,
  periods,
  currency,
  open,
  failed,
  onOpen,
  onClose,
}: {
  detail: Detail | undefined;
  periods: string[];
  currency: string | null;
  open: boolean;
  failed: boolean;
  onOpen: () => void;
  onClose: () => void;
}) {
  if (open) {
    return (
      <div style={backPanelStyle} data-testid="subscore-back-revenue_earnings">
        {detail ? (
          <FundamentalCardBack
            detail={detail}
            periods={periods}
            currency={currency}
            label="Revenue & earnings"
            onClose={onClose}
          />
        ) : (
          <FundamentalBackPlaceholder failed={failed} onClose={onClose} />
        )}
      </div>
    );
  }

  // By KEY, never by position — series order is the compute's business, and a
  // positional index silently charts net income as revenue the day that order
  // changes.
  const pick = (k: string) =>
    detail?.series.find((s) => s.key === k)?.values ?? [];
  const rev = pick("total_revenue_ttm");
  const ni = pick("net_income_ttm");
  const fcf = pick("fcf_ttm");

  return (
    <button
      type="button"
      onClick={onOpen}
      style={tileButtonStyle}
      data-testid="subscore-revenue_earnings"
    >
      <span style={labelStyle}>Revenue &amp; earnings</span>
      <div
        style={{
          fontSize: 22,
          fontWeight: 700,
          margin: "6px 0",
          color: "var(--text-primary)",
        }}
      >
        {fmtCompactUsd(rev.at(-1))}
      </div>
      {/* Reuses FundamentalSparkline so the eighth card's chart cannot drift
          from the seven beside it. */}
      {rev.filter((v) => v != null).length >= 2 ? (
        <FundamentalSparkline
          values={rev}
          dates={periods}
          label="Revenue TTM"
          stroke="var(--text-secondary)"
        />
      ) : null}
      <div
        style={{
          display: "flex",
          gap: 12,
          fontSize: 10,
          color: "var(--text-muted)",
          marginTop: 6,
        }}
      >
        <span>net income {fmtCompactUsd(ni.at(-1))}</span>
        <span>FCF {fmtCompactUsd(fcf.at(-1))}</span>
      </div>
      {/* Not "no direction claimed" like a subscore tile: this card is not a
          member of the validated set at all, and a footer that read the same
          would place it in one. */}
      <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 4 }}>
        descriptive · not scored
      </div>
    </button>
  );
}
