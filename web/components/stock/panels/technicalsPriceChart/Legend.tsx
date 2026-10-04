"use client";

import { type OverlayMode } from "./storage";

export function Legend({
  mode,
  showVwap,
  showChanlun,
}: {
  mode: OverlayMode;
  showVwap: boolean;
  showChanlun: boolean;
}) {
  const item = (color: string, label: string) => (
    <span
      key={label}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        marginRight: 12,
      }}
    >
      <span
        style={{
          width: 12,
          height: 2,
          background: color,
          display: "inline-block",
        }}
      />
      <span style={{ fontSize: 10, color: "var(--text-muted)" }}>{label}</span>
    </span>
  );
  const labels =
    mode === "sma"
      ? (["SMA20", "SMA50", "SMA200"] as const)
      : (["EMA5", "EMA20", "EMA50"] as const);
  return (
    <div style={{ marginTop: 6 }}>
      {item("var(--text-primary)", "PRICE")}
      {item("var(--accent-warm)", labels[0])}
      {item("var(--accent-vol)", labels[1])}
      {item("var(--accent-vivid)", labels[2])}
      {showVwap && item("var(--accent-cool)", "VWAP ⚓")}
      {showChanlun && item("var(--text-secondary)", "Zen 笔·中枢·买卖点")}
      {showChanlun && item("var(--accent-warm)", "线段·段级中枢")}
    </div>
  );
}

// MACD sub-pane legend: wide muted slow (structural) + split green/red fast
// (tactical), with the directional signal badge right-aligned. Mirrors the
// retired OscillatorChart swatches.
export function MacdLegend({
  signal,
}: {
  signal: { text: string; color: string } | null;
}) {
  return (
    <div
      style={{
        marginTop: 4,
        display: "flex",
        gap: 16,
        alignItems: "center",
      }}
    >
      <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
        <span
          style={{
            width: 14,
            height: 9,
            background: "var(--accent-vol)",
            opacity: 0.5,
            display: "inline-block",
            borderRadius: 1,
          }}
        />
        <span style={{ fontSize: 10, color: "var(--text-muted)" }}>
          SLOW 55/89/34 · structural
        </span>
      </span>
      <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
        <span
          style={{ display: "inline-flex", width: 8, height: 9 }}
          aria-hidden
        >
          <span style={{ flex: 1, background: "var(--positive)" }} />
          <span style={{ flex: 1, background: "var(--negative)" }} />
        </span>
        <span style={{ fontSize: 10, color: "var(--text-muted)" }}>
          FAST 13/21/9 · tactical
        </span>
      </span>
      {signal && (
        <span
          data-testid="technicals-macd-signal"
          style={{
            marginLeft: "auto",
            fontFamily: "var(--font-mono)",
            fontSize: 11,
            letterSpacing: 1,
            fontWeight: 700,
            color: signal.color,
          }}
        >
          {signal.text.toUpperCase()}
        </span>
      )}
    </div>
  );
}
