export function PersistOnlyBadge() {
  return (
    <span
      style={{
        fontFamily: "var(--font-mono)",
        fontSize: 9,
        letterSpacing: 1,
        textTransform: "uppercase",
        padding: "1px 4px",
        background: "color-mix(in srgb, var(--info, #3a8fd6) 12%, transparent)",
        color: "var(--info, #3a8fd6)",
        borderRadius: 2,
        whiteSpace: "nowrap",
      }}
    >
      [persist-only · no model in v1]
    </span>
  );
}
