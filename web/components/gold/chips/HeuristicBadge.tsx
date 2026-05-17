export function HeuristicBadge({
  reason = "heuristic, not yet calibrated",
}: {
  reason?: string;
}) {
  return (
    <span
      style={{
        fontFamily: "var(--font-mono)",
        fontSize: 9,
        letterSpacing: 1,
        textTransform: "uppercase",
        padding: "1px 4px",
        background:
          "color-mix(in srgb, var(--warning, #f5a623) 12%, transparent)",
        color: "var(--warning, #f5a623)",
        borderRadius: 2,
        whiteSpace: "nowrap",
      }}
    >
      [{reason}]
    </span>
  );
}
