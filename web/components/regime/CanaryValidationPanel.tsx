"use client";

import type { components } from "@/lib/types";
import { regimeApi } from "@/lib/regime/api";
import { useSyncHook } from "@/lib/regime/useSyncHook";

type Validation = components["schemas"]["CanaryValidationResponse"];

export default function CanaryValidationPanel() {
  const { data, error } = useSyncHook<Validation>(
    {
      endpoint: regimeApi.canaryValidation(),
      hasPost: false,
    },
    true,
  );
  if (error || !data) {
    return (
      <div data-testid="canary-validation-empty">
        No completed canary backtest at the current composite_version yet.
      </div>
    );
  }
  return (
    <article data-testid="canary-validation-panel" style={{ maxWidth: "100%" }}>
      <pre
        style={{
          whiteSpace: "pre-wrap",
          fontSize: 11,
          lineHeight: 1.6,
          fontFamily: "var(--font-mono)",
          color: "var(--text-primary)",
        }}
      >
        {data.rendered_markdown}
      </pre>
    </article>
  );
}
