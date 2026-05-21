type Tone = "positive" | "negative" | "warning" | "muted" | "default";

const TONE_COLOR: Record<Tone, string> = {
  positive: "var(--positive)",
  negative: "var(--negative)",
  warning: "var(--warning)",
  muted: "var(--text-muted)",
  default: "var(--text-primary)",
};

type Props = {
  label: string;
  value: string;
  sub?: string;
  tone?: Tone;
};

export function ExposureTile({ label, value, sub, tone = "default" }: Props) {
  return (
    <div
      data-testid="exposure-tile"
      style={{
        background: "var(--bg-panel)",
        border: "1px solid var(--border-dim)",
        borderRadius: 4,
        padding: "10px 14px",
        fontFamily: "var(--font-mono)",
        minWidth: 0,
      }}
    >
      <div
        style={{
          fontSize: 10,
          letterSpacing: 1.5,
          color: "var(--text-muted)",
          textTransform: "uppercase",
          marginBottom: 4,
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontSize: 22,
          fontWeight: 700,
          color: TONE_COLOR[tone],
          whiteSpace: "nowrap",
        }}
      >
        {value}
      </div>
      {sub && (
        <div
          style={{
            fontSize: 11,
            color: "var(--text-secondary)",
            marginTop: 2,
          }}
        >
          {sub}
        </div>
      )}
    </div>
  );
}
