import type { components } from "@/lib/types";

type S = components["schemas"]["GoldStructuralPostureModel"];

export function StructuralPostureText({ structural }: { structural: S }) {
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
      A POSTURE CONTEXT (long-horizon) · {structural.narrative_text}
    </p>
  );
}
