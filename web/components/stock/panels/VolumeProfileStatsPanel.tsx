"use client";

import type { VolumeProfileStats } from "@/lib/lwc/volumeProfile";

const BIAS_COLOR: Record<VolumeProfileStats["bias"], string> = {
  bullish: "var(--positive)",
  bearish: "var(--negative)",
  balanced: "var(--text-muted)",
};

const BIAS_NOTE: Record<VolumeProfileStats["bias"], string> = {
  bullish: "above value",
  bearish: "below value",
  balanced: "inside value",
};

function Tile({
  label,
  value,
  color,
  note,
}: {
  label: string;
  value: string;
  color?: string;
  note?: string;
}) {
  return (
    <div style={{ minWidth: 96 }}>
      <div
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 10,
          letterSpacing: 1.5,
          textTransform: "uppercase",
          color: "var(--text-muted)",
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 15,
          fontWeight: 700,
          color: color ?? "var(--text-primary)",
          lineHeight: 1.4,
        }}
      >
        {value}
      </div>
      {note && (
        <div style={{ fontSize: 10, color: "var(--text-muted)" }}>{note}</div>
      )}
    </div>
  );
}

/**
 * Readout for whatever the volume profile currently covers. Values come from
 * the chart primitive rather than being recomputed here, so the numbers always
 * match the bars actually drawn — pan or zoom and these follow.
 */
export function VolumeProfileStatsPanel({
  stats,
}: {
  stats: VolumeProfileStats | null;
}) {
  if (!stats) return null;
  const f = (v: number | null) => (v == null ? "–" : v.toFixed(2));
  return (
    <div
      data-testid="volume-profile-stats"
      style={{
        display: "flex",
        flexWrap: "wrap",
        gap: 18,
        marginTop: 8,
        padding: "8px 10px",
        background: "var(--bg-panel-raised)",
        border: "1px solid var(--border-dim)",
        borderRadius: 4,
      }}
    >
      <Tile label="POC" value={f(stats.poc)} color="var(--warning)" />
      <Tile label="VAH" value={f(stats.vah)} />
      <Tile label="VAL" value={f(stats.val)} />
      <Tile
        label="Nearest R"
        value={f(stats.nearestResistance)}
        color="var(--negative)"
        note={`${stats.resistanceCount} zone${stats.resistanceCount === 1 ? "" : "s"}`}
      />
      <Tile
        label="Nearest S"
        value={f(stats.nearestSupport)}
        color="var(--positive)"
        note={`${stats.supportCount} zone${stats.supportCount === 1 ? "" : "s"}`}
      />
      <Tile
        label="Bias"
        value={stats.bias}
        color={BIAS_COLOR[stats.bias]}
        note={BIAS_NOTE[stats.bias]}
      />
    </div>
  );
}
