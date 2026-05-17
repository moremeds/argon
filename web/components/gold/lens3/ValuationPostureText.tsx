import type { components } from "@/lib/types";

type V = components["schemas"]["GoldValuationPostureModel"];

export function ValuationPostureText({ valuation }: { valuation: V }) {
  return (
    <p
      style={{
        fontFamily: "var(--font-mono)",
        fontSize: 11,
        lineHeight: 1.5,
        color: "var(--text-secondary, #9aa3b2)",
        margin: 0,
      }}
    >
      {valuation.narrative_text}
    </p>
  );
}
