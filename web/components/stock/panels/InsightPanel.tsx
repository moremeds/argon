import type { CSSProperties, ReactNode } from "react";

const sectionHeading: CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: 9,
  color: "var(--text-muted)",
  letterSpacing: 0.8,
  textTransform: "uppercase",
};

export function InsightPanel({
  heading,
  subheading,
  children,
  action,
  fullBleed = false,
}: {
  heading: string;
  subheading?: string;
  children: ReactNode;
  action?: ReactNode;
  fullBleed?: boolean;
}) {
  return (
    <section
      style={{
        border: "1px solid var(--border-dim)",
        borderRadius: 4,
        background: "var(--bg-panel)",
        padding: fullBleed ? 0 : 18,
        display: "flex",
        flexDirection: "column",
        gap: 12,
        height: "100%",
        minWidth: 0,
      }}
    >
      <div style={{ padding: fullBleed ? "18px 18px 0" : 0 }}>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "flex-start",
            gap: 12,
          }}
        >
          <div style={sectionHeading}>{heading}</div>
          {action}
        </div>
        {subheading && (
          <div
            style={{
              fontSize: 13,
              lineHeight: 1.45,
              color: "var(--text-primary)",
              marginTop: 5,
            }}
          >
            {subheading}
          </div>
        )}
      </div>
      <div style={{ padding: fullBleed ? "0 18px 18px" : 0 }}>{children}</div>
    </section>
  );
}

export function InsightStatusBanner({
  text,
  severity = "warning",
}: {
  text: string;
  severity?: "warning" | "negative" | "info";
}) {
  const color =
    severity === "negative"
      ? "var(--negative)"
      : severity === "info"
        ? "var(--text-secondary)"
        : "var(--warning)";
  return (
    <div
      style={{
        padding: 8,
        background: "var(--bg-panel)",
        border: `1px dashed ${color}`,
        borderRadius: 4,
        fontFamily: "var(--font-mono)",
        fontSize: 11,
        color,
      }}
    >
      {text}
    </div>
  );
}
