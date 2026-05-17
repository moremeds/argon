"use client";

import type { CSSProperties } from "react";
import { useRouter, useSearchParams } from "next/navigation";

export function ScannerFilters() {
  const router = useRouter();
  const params = useSearchParams();
  const typeFOnly = params.get("type_f_only") === "true";
  const tier1Only = params.get("tier_1_only") === "true";

  function toggle(key: string, value: boolean) {
    const next = new URLSearchParams(params.toString());
    if (value) next.set(key, "true");
    else next.delete(key);
    const q = next.toString();
    router.push(`/scanner${q ? `?${q}` : ""}`);
  }

  const checkboxStyle: CSSProperties = {
    fontFamily: "var(--font-mono)",
    fontSize: 11,
    color: "var(--text-muted)",
    letterSpacing: 0.5,
    marginRight: 24,
    cursor: "pointer",
  };

  return (
    <div style={{ marginBottom: 16 }}>
      <label style={checkboxStyle}>
        <input
          key={`type-f-${typeFOnly}`}
          type="checkbox"
          defaultChecked={typeFOnly}
          onChange={(e) => toggle("type_f_only", e.target.checked)}
          style={{ marginRight: 6 }}
        />
        Type F only
      </label>
      <label style={checkboxStyle}>
        <input
          key={`tier-1-${tier1Only}`}
          type="checkbox"
          defaultChecked={tier1Only}
          onChange={(e) => toggle("tier_1_only", e.target.checked)}
          style={{ marginRight: 6 }}
        />
        Tier 1 only
      </label>
    </div>
  );
}
