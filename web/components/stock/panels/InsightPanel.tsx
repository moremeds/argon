import type { CSSProperties, ReactNode } from "react";

const sectionHeading: CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: 9,
  color: "var(--text-muted)",
  letterSpacing: 1,
  textTransform: "uppercase",
  marginTop: 4,
};

export function InsightPanel({
  heading,
  subheading,
  children,
  fullBleed = false,
}: {
  heading: string;
  subheading?: string;
  children: ReactNode;
  fullBleed?: boolean;
}) {
  return (
    <section
      style={{
        border: "1px solid var(--border-dim)",
        borderRadius: 4,
        background: "var(--bg-panel)",
        padding: fullBleed ? 0 : 16,
        display: "flex",
        flexDirection: "column",
        gap: 8,
      }}
    >
      <div style={{ padding: fullBleed ? "16px 16px 0" : 0 }}>
        <div style={sectionHeading}>{heading}</div>
        {subheading && (
          <div
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 12,
              color: "var(--text-primary)",
            }}
          >
            {subheading}
          </div>
        )}
      </div>
      <div style={{ padding: fullBleed ? "0 16px 16px" : 0 }}>{children}</div>
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
