import type { CSSProperties, ReactNode } from "react";

type Props = {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  tone?: "default" | "positive" | "negative" | "warning";
  style?: CSSProperties;
};

const toneToColor: Record<NonNullable<Props["tone"]>, string> = {
  default: "var(--text-primary, #cfd2db)",
  positive: "var(--positive, #05ad98)",
  negative: "var(--negative, #e85d6c)",
  warning: "var(--warning, #f5a623)",
};

/**
 * Canonical mono-uppercase tile used across GOLD COMPASS surfaces.
 * Matches the Tile shape in VolMetricsCard for visual consistency.
 */
export function Tile({ label, value, sub, tone = "default", style }: Props) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 4,
        padding: 12,
        background: "var(--bg-panel, #0d1018)",
        border: "1px solid var(--border-dim, #1b2030)",
        borderRadius: 4,
        ...style,
      }}
    >
      <span
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 10,
          letterSpacing: 1.5,
          textTransform: "uppercase",
          color: "var(--text-muted, #6b7280)",
        }}
      >
        {label}
      </span>
      <span
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 22,
          fontWeight: 700,
          color: toneToColor[tone],
        }}
      >
        {value}
      </span>
      {sub != null && (
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 11,
            color: "var(--text-secondary, #9aa3b2)",
          }}
        >
          {sub}
        </span>
      )}
    </div>
  );
}
