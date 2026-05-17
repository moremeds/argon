import type { components } from "@/lib/types";

type Gates = components["schemas"]["ScannerGatesStatus"];
type GateStatus = Gates["earnings"];

function dot(status: GateStatus) {
  return status === "pass" ? "✓" : "✗";
}

function color(status: GateStatus) {
  return status === "pass" ? "var(--positive)" : "var(--negative)";
}

export function GatesIndicator({ gates }: { gates: Gates }) {
  return (
    <span
      style={{
        fontFamily: "var(--font-mono)",
        fontSize: 11,
        letterSpacing: 0.5,
        color: "var(--text-muted)",
      }}
    >
      gates:{" "}
      <span style={{ color: color(gates.earnings) }}>
        earnings {dot(gates.earnings)}
      </span>{" "}
      <span style={{ color: color(gates.liquidity) }}>
        liq {dot(gates.liquidity)}
      </span>{" "}
      <span style={{ color: color(gates.regime) }}>
        regime {dot(gates.regime)}
      </span>
    </span>
  );
}
