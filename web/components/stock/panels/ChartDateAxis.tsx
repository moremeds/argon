/** X-axis date ticks for the technicals time-series charts. Renders `count`
 * evenly-spaced YYYY-MM labels from the series' as_of dates. */
export function ChartDateAxis({
  dates,
  x,
  y,
  count = 6,
}: {
  dates: Array<string | null | undefined>;
  x: (i: number) => number;
  y: number;
  count?: number;
}) {
  const n = dates.length;
  if (n < 2) return null;
  const idxs = Array.from({ length: count }, (_, k) =>
    Math.round((k * (n - 1)) / (count - 1)),
  );
  return (
    <g>
      {idxs.map((i, k) => {
        const label = dates[i];
        if (!label) return null;
        const anchor = k === 0 ? "start" : k === count - 1 ? "end" : "middle";
        return (
          <text
            key={i}
            x={x(i)}
            y={y}
            fontSize={9}
            fill="var(--text-muted)"
            textAnchor={anchor}
            fontFamily="var(--font-mono)"
          >
            {label.slice(0, 7)}
          </text>
        );
      })}
    </g>
  );
}
