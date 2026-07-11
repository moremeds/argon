import type { ReactNode } from "react";

export function AnalyticalSeriesPanel({
  title,
  subtitle,
  headline,
  children,
}: {
  title: string;
  subtitle?: string;
  headline?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div
      style={{
        background: "var(--bg-panel)",
        border: "1px solid var(--border-dim)",
        borderRadius: 4,
        padding: 16,
        fontFamily: "var(--font-mono)",
      }}
    >
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          justifyContent: "space-between",
          alignItems: "baseline",
          columnGap: 12,
          rowGap: 6,
          marginBottom: subtitle || headline ? 4 : 12,
        }}
      >
        <div>
          {subtitle && (
            <div
              style={{
                fontSize: 9,
                letterSpacing: 1,
                textTransform: "uppercase",
                color: "var(--text-muted)",
              }}
            >
              {subtitle}
            </div>
          )}
          <div
            style={{
              fontSize: 11,
              letterSpacing: 1,
              textTransform: "uppercase",
              color: "var(--text-secondary)",
            }}
          >
            {title}
          </div>
        </div>
        {headline && (
          <div
            style={{
              fontSize: 16,
              color: "var(--accent-bg)",
              fontWeight: 600,
              minWidth: 0,
            }}
          >
            {headline}
          </div>
        )}
      </div>
      <div>{children}</div>
    </div>
  );
}
