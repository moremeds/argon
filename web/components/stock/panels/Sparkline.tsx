// Hand-rolled fixed-width sparkline for the OI movers TAPE column.
// Renders 12 bars (or whatever the array length is); empty / all-zero
// inputs produce a baseline-only SVG so the column width stays stable.

type Props = {
  values: ReadonlyArray<number>;
  width?: number;
  height?: number;
  color?: string;
  ariaLabel?: string;
};

export function Sparkline({
  values,
  width = 80,
  height = 18,
  color = "var(--accent-bg)",
  ariaLabel,
}: Props) {
  const n = values.length;
  if (n === 0) {
    return (
      <svg
        role="img"
        aria-label={ariaLabel ?? "no-data sparkline"}
        width={width}
        height={height}
      />
    );
  }
  const max = Math.max(...values);
  const gap = 1;
  const barW = Math.max(1, (width - gap * (n - 1)) / n);
  return (
    <svg
      role="img"
      aria-label={ariaLabel ?? "intraday volume sparkline"}
      width={width}
      height={height}
    >
      {values.map((v, i) => {
        const h = max > 0 ? (v / max) * height : 0;
        return (
          <rect
            key={i}
            x={i * (barW + gap)}
            // SVG y-axis is top-down — anchor bars at the bottom.
            y={height - h}
            width={barW}
            height={h}
            fill={color}
          />
        );
      })}
    </svg>
  );
}
