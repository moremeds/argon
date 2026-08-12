import type { components } from "@/lib/types";
import { fmtDecimal, fmtPct } from "@/lib/formatters";
import { FundamentalSparkline } from "./FundamentalSparkline";
import { LABELS, labelStyle, tileButtonStyle } from "./fundamentalShared";

type Subscore = components["schemas"]["FundamentalSubscore"];
type Pct = components["schemas"]["FundamentalPercentile"];

/** 0.913 -> "91st". Rounded to a whole percentile: the third decimal of a rank
 *  among 253 names is noise, and printing it would imply precision we lack. */
function ordinal(p: number): string {
  const n = Math.round(p * 100);
  const rem100 = n % 100;
  if (rem100 >= 11 && rem100 <= 13) return `${n}th`;
  return `${n}${["th", "st", "nd", "rd"][n % 10] ?? "th"}`;
}

export function PercentileTag({ pct }: { pct: Pct | null | undefined }) {
  if (!pct) return null;
  return (
    // No colour ramp. A percentile locates the name in its panel; it is not a
    // quality score and not an expected return (zero gross alpha measured
    // 2026-08-12), so painting it green would assert something untrue.
    <span style={{ ...labelStyle, fontSize: 9, letterSpacing: 0.5 }}>
      {ordinal(pct.percentile)} of {pct.n}
    </span>
  );
}

function formatValue(s: Subscore): string {
  if (s.value == null) return "na";
  return s.unit === "ratio" ? fmtPct(s.value, 1) : `${fmtDecimal(s.value, 2)}x`;
}

export function SubscoreTile({
  s,
  dates,
  onOpen,
}: {
  s: Subscore;
  dates: string[];
  onOpen: () => void;
}) {
  const suppressed = s.suppressed_by.length > 0;
  const series = s.series ?? [];
  return (
    <button
      type="button"
      onClick={onOpen}
      style={tileButtonStyle}
      data-testid={`subscore-${s.feature}`}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
          gap: 8,
        }}
      >
        <span style={labelStyle}>{LABELS[s.feature] ?? s.feature}</span>
        <PercentileTag pct={s.percentile} />
      </div>
      <div
        style={{
          fontSize: 22,
          fontWeight: 700,
          color: s.value == null ? "var(--text-muted)" : "var(--text-primary)",
          margin: "6px 0",
        }}
      >
        {formatValue(s)}
      </div>
      {series.length ? (
        <FundamentalSparkline
          values={series}
          dates={dates}
          label={LABELS[s.feature] ?? s.feature}
          stroke="var(--text-secondary)"
        />
      ) : null}
      {suppressed ? (
        <div
          style={{
            fontSize: 10,
            color: "var(--warning)",
            lineHeight: 1.4,
            marginTop: 6,
          }}
        >
          suppressed · {s.suppressed_by.join(", ")}
        </div>
      ) : (
        <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 6 }}>
          {s.direction === "higher_better"
            ? "higher better"
            : "no direction claimed"}
        </div>
      )}
    </button>
  );
}
