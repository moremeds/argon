import type { ReactNode } from "react";

export type Tone = "positive" | "negative" | "warning" | "neutral";
export type ProviderGridValue = string | number | null | undefined;

export const labelStyle = {
  fontFamily: "var(--font-mono)",
  fontSize: 9,
  color: "var(--text-muted)",
  letterSpacing: 1,
  textTransform: "uppercase" as const,
};

export function toneColor(tone: Tone): string {
  if (tone === "positive") return "var(--positive)";
  if (tone === "negative") return "var(--negative)";
  if (tone === "warning") return "var(--warning)";
  return "var(--neutral)";
}

export function plainText(value: string | null | undefined): string {
  return (value ?? "")
    .replaceAll("needs_check", "pending validation")
    .replaceAll("do_not_sell", "do not sell premium")
    .replaceAll("_", " ");
}

export function shortDate(value: string | null | undefined): string {
  if (!value) return "unknown";
  return value.slice(0, 10);
}

export function clipped(value: string, max = 120): string {
  if (value.length <= max) return value;
  return `${value.slice(0, max - 1).trim()}...`;
}

export function tidyProviderValue(value: ProviderGridValue): string {
  if (value == null || value === "") return "None";
  const text = String(value);
  if (!/^-?\d+(\.\d+)?$/.test(text)) return text;
  const n = Number(text);
  if (!Number.isFinite(n)) return text;
  return new Intl.NumberFormat("en-US", {
    maximumFractionDigits: Math.abs(n) < 1 ? 4 : 2,
  }).format(n);
}

export function SmallHeading({ children }: { children: ReactNode }) {
  return (
    <div
      style={{ color: "var(--text-primary)", fontSize: 12, fontWeight: 700 }}
    >
      {children}
    </div>
  );
}

export function CompactNote({ label, value }: { label: string; value: string }) {
  return (
    <div
      style={{
        border: "1px solid var(--border-dim)",
        borderRadius: 4,
        padding: 8,
      }}
    >
      <SmallHeading>{label}</SmallHeading>
      <div
        style={{
          color: "var(--text-secondary)",
          fontSize: 12,
          lineHeight: 1.4,
        }}
      >
        {plainText(clipped(value, 110))}
      </div>
    </div>
  );
}

export function ProviderKeyValueGrid({
  items,
}: {
  items: { label: string; value: ProviderGridValue }[];
}) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 120px), 1fr))",
        gap: "8px 12px",
      }}
    >
      {items.map((item) => (
        <div key={item.label}>
          <div
            style={{
              color: "var(--text-primary)",
              fontSize: 12,
              fontWeight: 700,
            }}
          >
            {item.label}
          </div>
          <div style={{ color: "var(--text-primary)", fontSize: 13 }}>
            {plainText(tidyProviderValue(item.value))}
          </div>
        </div>
      ))}
    </div>
  );
}

export function BulletList({
  items,
  limit = 4,
}: {
  items: (string | null | undefined)[];
  limit?: number;
}) {
  const visible = items.filter(Boolean).slice(0, limit) as string[];
  if (visible.length === 0) {
    return <div style={{ color: "var(--text-muted)", fontSize: 12 }}>None</div>;
  }
  return (
    <div style={{ display: "grid", gap: 5 }}>
      {visible.map((item) => (
        <div
          key={item}
          style={{ color: "var(--text-secondary)", fontSize: 12 }}
        >
          {plainText(item)}
        </div>
      ))}
    </div>
  );
}

export function AnalysisCard({
  title,
  subtitle,
  tone,
  children,
}: {
  title: string;
  subtitle?: string | null;
  tone: Tone;
  children: ReactNode;
}) {
  return (
    <div
      style={{
        border: `1px solid ${tone === "neutral" ? "var(--border-dim)" : toneColor(tone)}`,
        borderRadius: 4,
        background: "var(--bg-panel)",
        height: "100%",
        minHeight: 0,
        padding: "12px 14px",
        display: "flex",
        flexDirection: "column",
        gap: 8,
        overflowWrap: "anywhere",
      }}
    >
      <div>
        <div
          style={{ display: "flex", justifyContent: "space-between", gap: 10 }}
        >
          <div
            style={{
              color: "var(--text-primary)",
              fontSize: 15,
              fontWeight: 700,
              lineHeight: 1.25,
            }}
          >
            {title}
          </div>
          {tone !== "neutral" && (
            <span
              aria-label={`${tone} signal`}
              style={{
                width: 8,
                height: 8,
                marginTop: 5,
                flex: "0 0 auto",
                background: toneColor(tone),
              }}
            />
          )}
        </div>
        {subtitle && (
          <div
            style={{
              color: "var(--text-muted)",
              fontFamily: "var(--font-mono)",
              fontSize: 10,
              marginTop: 4,
            }}
          >
            {subtitle}
          </div>
        )}
      </div>
      {children}
    </div>
  );
}
