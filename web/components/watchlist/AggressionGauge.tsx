type Props = { value: number | null | undefined };

export function AggressionGauge({ value }: Props) {
  const r = 22;
  const c = 2 * Math.PI * r;
  const pct = value ?? 0;
  const offset = c * (1 - pct);
  const label = value == null ? "—" : `${Math.round(pct * 100)}`;
  const color =
    value == null
      ? "var(--text-muted)"
      : pct > 0.7
        ? "var(--positive)"
        : pct < 0.3
          ? "var(--negative)"
          : "var(--warning)";
  return (
    <div
      style={{
        display: "inline-flex",
        flexDirection: "column",
        alignItems: "center",
      }}
    >
      <svg width={56} height={56} viewBox="0 0 56 56">
        <circle
          cx="28"
          cy="28"
          r={r}
          fill="none"
          stroke="var(--border-dim)"
          strokeWidth={4}
        />
        <circle
          cx="28"
          cy="28"
          r={r}
          fill="none"
          stroke={color}
          strokeWidth={4}
          strokeDasharray={c}
          strokeDashoffset={offset}
          transform="rotate(-90 28 28)"
          strokeLinecap="round"
        />
        <text
          x="28"
          y="32"
          textAnchor="middle"
          fontFamily="var(--font-mono)"
          fontSize="11"
          fill="var(--text-primary)"
        >
          {label}
        </text>
      </svg>
      <span
        style={{
          fontSize: 9,
          fontFamily: "var(--font-mono)",
          color: "var(--text-muted)",
          letterSpacing: 0.5,
        }}
      >
        FLOW AGGR
      </span>
    </div>
  );
}
