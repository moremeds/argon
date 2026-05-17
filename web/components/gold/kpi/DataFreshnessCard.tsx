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
  const worst = sources.reduce((acc, s) =>
    s.stale_seconds > acc.stale_seconds ? s : acc,
  );
  return (
    <Tile
      label="DATA FRESHNESS"
      tone={tone(worst.stale_seconds)}
      value={`${ageLabel(worst.stale_seconds)} · ${worst.id}`}
      sub={
        <span style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {sources.map((s) => (
            <span key={s.id}>
              {s.id} {ageLabel(s.stale_seconds)}
            </span>
          ))}
        </span>
      }
    />
  );
}
