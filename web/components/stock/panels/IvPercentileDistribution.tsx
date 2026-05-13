import { toNum } from "@/lib/formatters";
import { AnalyticalSeriesPanel } from "./AnalyticalSeriesPanel";

export type IvHistogramBin = {
  lo: string | number;
  hi: string | number;
  count: number;
};

export type IvPercentileDist = {
  bins: IvHistogramBin[];
  current_iv?: string | number | null;
  current_pctile?: string | number | null;
};

export function IvPercentileDistribution({ data }: { data: IvPercentileDist }) {
  const bins = data.bins ?? [];
  if (bins.length === 0) {
    return (
      <AnalyticalSeriesPanel title="IV %ile Distribution" subtitle="Last 1y">
        <div style={{ color: "var(--text-muted)", fontSize: 11 }}>
          No IV history
        </div>
      </AnalyticalSeriesPanel>
    );
  }
  const W = 400;
  const H = 220;
  const M = { top: 8, right: 16, bottom: 24, left: 36 };
  const maxCount = Math.max(1, ...bins.map((b) => b.count));
  const innerW = W - M.left - M.right;
  const innerH = H - M.top - M.bottom;
  const barW = innerW / bins.length;
  const currentIv = toNum(data.current_iv);
  const lowIv = toNum(bins[0].lo);
  const highIv = toNum(bins[bins.length - 1].hi);
  let currentX: number | null = null;
  if (
    currentIv != null &&
    lowIv != null &&
    highIv != null &&
    highIv !== lowIv
  ) {
    const frac = (currentIv - lowIv) / (highIv - lowIv);
    currentX = M.left + Math.max(0, Math.min(1, frac)) * innerW;
  }

  const headline =
    data.current_pctile != null
      ? `${toNum(data.current_pctile)?.toFixed(0)}th %ile`
      : undefined;

  return (
    <AnalyticalSeriesPanel
      title="IV %ile Distribution"
      subtitle="Last 1y"
      headline={headline}
    >
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} role="img">
        {bins.map((b, i) => {
          const h = innerH * (b.count / maxCount);
          return (
            <rect
              key={i}
              x={M.left + i * barW + 1}
              y={M.top + (innerH - h)}
              width={barW - 2}
              height={h}
              fill="var(--accent-bg)"
              opacity={0.7}
            />
          );
        })}
        {currentX !== null && (
          <line
            x1={currentX}
            x2={currentX}
            y1={M.top}
            y2={H - M.bottom}
            stroke="var(--warning)"
            strokeWidth={2}
            strokeDasharray="3,3"
          />
        )}
        {lowIv != null && (
          <text x={M.left} y={H - 4} fontSize={9} fill="var(--text-muted)">
            {(lowIv * 100).toFixed(1)}%
          </text>
        )}
        {highIv != null && (
          <text
            x={W - M.right}
            y={H - 4}
            fontSize={9}
            textAnchor="end"
            fill="var(--text-muted)"
          >
            {(highIv * 100).toFixed(1)}%
          </text>
        )}
      </svg>
    </AnalyticalSeriesPanel>
  );
}
