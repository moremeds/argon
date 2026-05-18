import type { components } from "@/lib/types";

import { Tile } from "../Tile";

type Source = components["schemas"]["GoldDataFreshnessSource"];

function ageLabel(stale: number): string {
  if (stale < 60) return `${stale}s`;
  if (stale < 3600) return `${Math.round(stale / 60)}m`;
  if (stale < 86400) return `${Math.round(stale / 3600)}h`;
  return `${Math.round(stale / 86400)}d`;
}

function tone(stale: number): "positive" | "warning" | "negative" {
  if (stale < 60 * 60 * 24) return "positive";
  if (stale < 60 * 60 * 24 * 3) return "warning";
  return "negative";
}

export function DataFreshnessCard({ sources }: { sources: Source[] }) {
  if (sources.length === 0) {
    return <Tile label="DATA FRESHNESS" value="—" sub="No sources reporting" />;
  }
  const missing = sources.filter((s) => s.status === "missing");
  const reporting = sources.filter(
    (s) => s.status !== "missing" && s.stale_seconds != null,
  );
  const worst = reporting.reduce<Source | null>(
    (acc, s) =>
      acc == null || (s.stale_seconds ?? 0) > (acc.stale_seconds ?? 0) ? s : acc,
    null,
  );
  const value =
    missing.length > 0
      ? `${missing.length} missing`
      : worst
        ? `${ageLabel(worst.stale_seconds ?? 0)} · ${worst.id}`
        : "—";
  return (
    <Tile
      label="DATA FRESHNESS"
      tone={missing.length > 0 ? "negative" : tone(worst?.stale_seconds ?? 0)}
      value={value}
      sub={
        <span style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {sources.map((s) => (
            <span key={s.id}>
              {s.id}{" "}
              {s.status === "missing" || s.stale_seconds == null
                ? "missing"
                : ageLabel(s.stale_seconds)}
            </span>
          ))}
        </span>
      }
    />
  );
}
