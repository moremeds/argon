import type { components } from "@/lib/types";

type S = components["schemas"]["GoldStructuralPostureModel"];

export function StructuralPostureText({ structural }: { structural: S }) {
  return (
    <details className="data-details">
      <summary>Publisher note</summary>
      <p className="cap">{structural.narrative_text}</p>
    </details>
  );
}
