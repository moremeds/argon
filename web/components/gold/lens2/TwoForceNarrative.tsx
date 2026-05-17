import type { components } from "@/lib/types";

type C = components["schemas"]["GoldCyclicalPostureModel"];

export function TwoForceNarrative({ cyclical }: { cyclical: C }) {
  const tf = cyclical.two_force_text;
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "1fr 1fr",
        gap: 12,
        padding: 12,
        background: "var(--bg-panel, #0d1018)",
        border: "1px solid var(--border-dim, #1b2030)",
        borderRadius: 4,
      }}
    >
      <div>
        <div
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 10,
            letterSpacing: 1.5,
            textTransform: "uppercase",
            color: "var(--text-muted, #6b7280)",
            marginBottom: 4,
          }}
        >
          DISCOUNT-RATE CHANNEL
        </div>
        <div
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 11,
            color: "var(--text-secondary, #9aa3b2)",
          }}
        >
          {tf?.discount_rate ?? "—"}
        </div>
      </div>
      <div>
        <div
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 10,
            letterSpacing: 1.5,
            textTransform: "uppercase",
            color: "var(--text-muted, #6b7280)",
            marginBottom: 4,
          }}
        >
          HEDGE-DEMAND CHANNEL
        </div>
        <div
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 11,
            color: "var(--text-secondary, #9aa3b2)",
          }}
        >
          {tf?.hedge_demand ?? "—"}
        </div>
      </div>
    </div>
  );
}
