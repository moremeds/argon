// The stat tile: mono uppercase label, 22px bold value, muted sub-line.
// Shared by the stock page's VolMetricsCard and GexLevelTiles (I-105). The
// sub fallback is a no-break space so the sub-line keeps its height.
const tileStyle: React.CSSProperties = {
  background: "var(--bg-panel)",
  border: "1px solid var(--border-dim)",
  borderRadius: 4,
  padding: "12px 14px",
  display: "flex",
  flexDirection: "column",
  gap: 6,
  minWidth: 0,
};

const labelStyle: React.CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: 10,
  letterSpacing: 1.5,
  textTransform: "uppercase",
  color: "var(--text-muted)",
};

const valueStyle: React.CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontWeight: 700,
  fontSize: 22,
  color: "var(--text-primary)",
  lineHeight: 1,
};

const subStyle: React.CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: 11,
  color: "var(--text-muted)",
};

export function Tile({
  label,
  value,
  sub,
  valueColor,
}: {
  label: string;
  value: string;
  sub?: string;
  valueColor?: string;
}) {
  return (
    <div style={tileStyle}>
      <div style={labelStyle}>{label}</div>
      <div style={{ ...valueStyle, color: valueColor ?? valueStyle.color }}>
        {value}
      </div>
      <div style={subStyle}>{sub ?? " "}</div>
    </div>
  );
}
