"use client";

import type { MagnetsResponse } from "@/lib/api";

type Levels = NonNullable<MagnetsResponse["levels"]>;

// Reference palette, deliberately NOT argon CSS tokens (spec §5.1). The colour
// IS the role — do not swap these for theme variables.
export const MAGNET_COLORS = {
  stretch: "#22d3ee", // cyan
  resistance: "#fb7185", // salmon
  last: "#facc15", // yellow
  support: "#4ade80", // green
  down: "#f59e0b", // amber
} as const;

const NO_EDGE = "0.618 extension — no measured edge";

export default function MagnetTable({ levels }: { levels: Levels | null }) {
  if (!levels)
    return (
      <div
        style={{ fontFamily: "var(--font-mono)", fontSize: 12, opacity: 0.6 }}
      >
        No confirmed swing — fewer than two ZigZag pivots at this threshold.
      </div>
    );

  const rows: { label: string; price: number; color: string; role: string }[] =
    [
      {
        label: "STRETCH",
        price: levels.stretch,
        color: MAGNET_COLORS.stretch,
        role: NO_EDGE,
      },
      {
        label: "RESISTANCE",
        price: levels.resistance,
        color: MAGNET_COLORS.resistance,
        role: "last confirmed swing high",
      },
      {
        label: "LAST",
        price: levels.last,
        color: MAGNET_COLORS.last,
        role: "current close",
      },
      {
        label: "SUPPORT",
        price: levels.support,
        color: MAGNET_COLORS.support,
        role: "last confirmed swing low",
      },
      {
        label: "DOWN",
        price: levels.down,
        color: MAGNET_COLORS.down,
        role: NO_EDGE,
      },
    ];

  return (
    <table
      style={{
        width: "100%",
        fontFamily: "var(--font-mono)",
        fontSize: 12,
        borderCollapse: "collapse",
      }}
    >
      <tbody>
        {rows.map((r) => (
          <tr
            key={r.label}
            style={{ borderBottom: "1px solid rgba(255,255,255,0.06)" }}
          >
            <td
              style={{
                color: r.color,
                fontWeight: 700,
                padding: "4px 8px 4px 0",
              }}
            >
              {r.label}
            </td>
            <td style={{ textAlign: "right", padding: "4px 12px 4px 0" }}>
              {r.price.toFixed(2)}
            </td>
            <td style={{ opacity: 0.65 }}>{r.role}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
