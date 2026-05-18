import type { components } from "@/lib/types";

type Flag = components["schemas"]["ScannerContextFlag"];

const COLOR_BY_LABEL: Record<string, string> = {
  "Extreme Fear": "var(--negative)",
  "Elevated Fear": "var(--negative)",
  Complacent: "var(--positive)",
};

export function ContextFlagBadge({ flag }: { flag: Flag }) {
  const color = COLOR_BY_LABEL[flag.label] ?? "var(--warning)";
  return (
    <span
      style={{
        color,
        fontFamily: "var(--font-mono)",
        fontSize: 11,
        letterSpacing: 0.5,
        marginRight: 12,
      }}
    >
      flag: {flag.label}
    </span>
  );
}
