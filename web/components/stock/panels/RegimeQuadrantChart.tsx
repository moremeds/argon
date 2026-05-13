import { toNum } from "@/lib/formatters";
import { AnalyticalSeriesPanel } from "./AnalyticalSeriesPanel";

export type RegimeQuadrantPoint = {
  date: string;
  rvol_pctile?: string | number | null | undefined;
  spy_corr_21?: string | number | null | undefined;
};

export type RegimeQuadrantLatest = {
  date: string;
  rvol_pctile?: string | number | null | undefined;
  spy_corr_21?: string | number | null | undefined;
  state: string;
};

export type RegimeQuadrantBlock = {
  points: RegimeQuadrantPoint[];
  latest?: RegimeQuadrantLatest | null;
  cutoff_corr?: string | number | null | undefined;
};

const STATE_LABELS: Record<
  string,
  { label: string; corner: string; gloss: string }
> = {
  GOLDILOCKS: {
    label: "Goldilocks",
    corner: "bl",
    gloss: "low vol, low corr — calm, idiosyncratic",
  },
  FRAGILE_CALM: {
    label: "Fragile Calm",
    corner: "tl",
    gloss: "low vol, high corr — quiet but tape-driven",
  },
  STOCK_PICKER: {
    label: "Stock Picker",
    corner: "br",
    gloss: "high vol, low corr — name-specific dispersion",
  },
  SYSTEMIC_PANIC: {
    label: "Systemic Panic",
    corner: "tr",
    gloss: "high vol, high corr — broad de-risking",
  },
};

export function RegimeQuadrantChart({ data }: { data: RegimeQuadrantBlock }) {
  const pts = data.points ?? [];
  if (pts.length === 0 && data.latest == null) {
    return (
      <AnalyticalSeriesPanel title="Regime Quadrant" subtitle="20 sessions">
        <div style={{ color: "var(--text-muted)", fontSize: 11 }}>
          SPY OHLC not seeded — run scripts/seed_spy_ohlc.py
        </div>
      </AnalyticalSeriesPanel>
    );
  }

  const W = 400;
  const H = 220;
  const M = { top: 16, right: 16, bottom: 24, left: 36 };
  const innerW = W - M.left - M.right;
  const innerH = H - M.top - M.bottom;

  // X: rvol_pctile 0–100. Y: spy_corr_21 -1..1.
  const x = (v: number) =>
    M.left + (Math.max(0, Math.min(100, v)) / 100) * innerW;
  const y = (v: number) =>
    M.top + (1 - (Math.max(-1, Math.min(1, v)) + 1) / 2) * innerH;

  const latestState = data.latest?.state ?? "";
  const cutoff = toNum(data.cutoff_corr);
  // Draw the horizontal divider at the classifier's actual cutoff (median corr,
  // or 0.5 fallback). Drawing at y(0) created a visual/state mismatch (#5).
  const cutoffY = cutoff != null ? y(cutoff) : y(0);

  return (
    <AnalyticalSeriesPanel title="Regime Quadrant" subtitle="20 sessions">
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} role="img">
        <line
          x1={x(50)}
          x2={x(50)}
          y1={M.top}
          y2={H - M.bottom}
          stroke="var(--chart-grid)"
          strokeDasharray="2,3"
        />
        <line
          x1={M.left}
          x2={W - M.right}
          y1={cutoffY}
          y2={cutoffY}
          stroke="var(--chart-grid)"
          strokeDasharray="2,3"
        />
        {cutoff != null && (
          <text
            x={W - M.right - 4}
            y={cutoffY - 3}
            fontSize={8}
            textAnchor="end"
            fill="var(--text-muted)"
          >
            corr cutoff = {cutoff.toFixed(2)}
          </text>
        )}
        <text
          x={M.left + 4}
          y={M.top + 10}
          fontSize={9}
          fill="var(--text-muted)"
        >
          Fragile Calm
        </text>
        <text
          x={W - M.right - 4}
          y={M.top + 10}
          fontSize={9}
          textAnchor="end"
          fill="var(--text-muted)"
        >
          Systemic Panic
        </text>
        <text
          x={M.left + 4}
          y={H - M.bottom - 4}
          fontSize={9}
          fill="var(--text-muted)"
        >
          Goldilocks
        </text>
        <text
          x={W - M.right - 4}
          y={H - M.bottom - 4}
          fontSize={9}
          textAnchor="end"
          fill="var(--text-muted)"
        >
          Stock Picker
        </text>
        {pts.map((p, i) => {
          const px = toNum(p.rvol_pctile);
          const py = toNum(p.spy_corr_21);
          if (px == null || py == null) return null;
          return (
            <circle
              key={i}
              cx={x(px)}
              cy={y(py)}
              r={2.5}
              fill="var(--accent-bg)"
              opacity={0.5}
            />
          );
        })}
        {data.latest &&
          toNum(data.latest.rvol_pctile) != null &&
          toNum(data.latest.spy_corr_21) != null && (
            <circle
              cx={x(toNum(data.latest.rvol_pctile)!)}
              cy={y(toNum(data.latest.spy_corr_21)!)}
              r={5}
              fill="var(--accent-bg)"
              stroke="var(--text-primary)"
              strokeWidth={1.5}
            />
          )}
        <text x={M.left} y={H - 4} fontSize={9} fill="var(--text-muted)">
          0 RVOL %ile 100
        </text>
      </svg>
      <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
        {Object.entries(STATE_LABELS).map(([key, v]) => (
          <span
            key={key}
            title={v.gloss}
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 10,
              padding: "2px 6px",
              border: "1px solid var(--border-dim)",
              borderRadius: 2,
              background:
                key === latestState ? "var(--accent-bg)" : "transparent",
              color:
                key === latestState
                  ? "var(--accent-text)"
                  : "var(--text-muted)",
              cursor: "help",
            }}
          >
            {v.label}
          </span>
        ))}
      </div>
      <div
        style={{
          marginTop: 6,
          fontSize: 10,
          color: "var(--text-muted)",
          lineHeight: 1.4,
        }}
      >
        {latestState && STATE_LABELS[latestState]
          ? `${STATE_LABELS[latestState].label}: ${STATE_LABELS[latestState].gloss}`
          : "Hover a tile for the meaning of each quadrant."}
      </div>
    </AnalyticalSeriesPanel>
  );
}
