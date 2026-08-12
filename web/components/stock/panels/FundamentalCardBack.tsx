import type { components } from "@/lib/types";
import { FundamentalBarChart } from "./FundamentalBarChart";

type Detail = components["schemas"]["FundamentalFeatureDetail"];

/**
 * Features with no validated direction. `gross_margin` and `op_margin` measured
 * INVERTED in the 2026-08-12 validation and `roe` is named by no rubric row, so
 * their ratio line gets a neutral stroke. The front already refuses to imply a
 * direction for these three; the back must not quietly reintroduce one.
 */
const NO_DIRECTION = new Set(["gross_margin", "op_margin", "roe"]);

const BASIS_NOTE: Record<string, string> = {
  ttm: "trailing twelve months",
  quarterly: "per quarter",
  // Deliberately direction-neutral. `roe` and `asset_turnover` put a TTM flow
  // OVER a point-in-time balance, while `neg_net_debt_ebitda` puts point-in-time
  // debt and cash over a TTM EBITDA — the other way round. One note has to be
  // true for all three, so it names the mix rather than an order.
  mixed: "mixes a four-quarter flow with a point-in-time balance",
};

export function FundamentalCardBack({
  detail,
  periods,
  currency,
  label,
}: {
  detail: Detail;
  periods: string[];
  currency: string | null;
  label: string;
}) {
  const inputs = detail.series.filter((s) => s.role === "input");
  const context = detail.series.filter((s) => s.role === "context");

  return (
    <div>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
          gap: 12,
        }}
      >
        <span
          style={{
            fontSize: 10,
            letterSpacing: 1.5,
            textTransform: "uppercase",
            color: "var(--text-muted)",
          }}
        >
          {label} · components
        </span>
        {/* A hint, not a control — the whole card is the control. Without this
            the way back is undiscoverable, since nothing on the flipped card
            looks clickable. */}
        <span
          style={{ fontSize: 10, color: "var(--text-muted)", opacity: 0.7 }}
        >
          click to flip back
        </span>
      </div>

      <div
        style={{
          fontSize: 10,
          color: "var(--text-muted)",
          margin: "4px 0 8px",
        }}
      >
        {`${detail.basis} · ${BASIS_NOTE[detail.basis] ?? detail.basis} · figures in ${currency ?? "an unreported currency"}`}
      </div>

      <FundamentalBarChart
        series={detail.series}
        ratio={detail.ratio}
        periods={periods}
        ratioUnit={detail.unit === "turns" ? "turns" : "ratio"}
        ratioStroke={
          NO_DIRECTION.has(detail.feature)
            ? "var(--text-secondary)"
            : "var(--accent-bg)"
        }
      />

      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: 12,
          fontSize: 10,
          color: "var(--text-muted)",
          marginTop: 6,
        }}
      >
        {inputs.map((s) => (
          <span key={s.key}>{s.label}</span>
        ))}
        {context.map((s) => (
          <span key={s.key} style={{ opacity: 0.6 }}>
            {s.label} (context)
          </span>
        ))}
      </div>
    </div>
  );
}
