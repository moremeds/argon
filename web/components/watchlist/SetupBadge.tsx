type Props = { type: string | null; direction: string | null };

function labelAndColor(
  t: string | null,
  d: string | null,
): { label: string; color: string } {
  if (t === "C" && d === "bull")
    return { label: "C-BULL", color: "var(--positive)" };
  if (t === "C" && d === "bear")
    return { label: "C-BEAR", color: "var(--negative)" };
  if (t === "F") return { label: "F-MULTI", color: "var(--info)" };
  return { label: "NEUTRAL", color: "var(--text-muted)" };
}

export function SetupBadge({ type, direction }: Props) {
  const { label, color } = labelAndColor(type, direction);
  return (
    <span
      style={{
        display: "inline-block",
        padding: "2px 6px",
        fontSize: 10,
        fontFamily: "var(--font-mono)",
        letterSpacing: 0.5,
        color: "var(--bg-base)",
        background: color,
        borderRadius: 2,
        fontWeight: 700,
      }}
    >
      {label}
    </span>
  );
}
