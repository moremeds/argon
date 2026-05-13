export function sparklinePath(
  values: number[],
  width: number,
  height: number,
): string {
  if (!values.length) return "";
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min;
  const step = values.length > 1 ? width / (values.length - 1) : 0;
  return values
    .map((v, i) => {
      const x = (i * step).toFixed(2).replace(/\.00$/, "");
      const yNum = range === 0 ? height / 2 : ((max - v) / range) * height;
      const y = yNum.toFixed(2).replace(/\.00$/, "");
      return `${i === 0 ? "M" : "L"}${x},${y}`;
    })
    .join(" ");
}

export function Sparkline({
  values,
  color = "var(--accent-bg)",
}: {
  values: number[];
  color?: string;
}) {
  const width = 200;
  const height = 30;
  const d = sparklinePath(values, width, height);
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
      <path d={d} fill="none" stroke={color} strokeWidth={1.2} />
    </svg>
  );
}
