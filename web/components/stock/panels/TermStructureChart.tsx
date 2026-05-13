import { toNum } from "@/lib/formatters";
import { finiteDomain, linearScale, pathFromPoints } from "@/lib/svgChart";
import type { Point } from "@/lib/svgChart";
import { AnalyticalSeriesPanel } from "./AnalyticalSeriesPanel";

export type TermStructureRow = {
  expiry: string;
  dte?: number | null;
  by_strike: Record<string, string | number | null>;
};

const STRIKE_COLORS: Record<string, string> = {
  "ATM-2": "var(--accent-vol)",
  "ATM-1": "var(--accent-vivid)",
  ATM: "var(--accent-bg)",
  "ATM+1": "var(--accent-warm)",
};
const ORDERED_STRIKES = ["ATM-2", "ATM-1", "ATM", "ATM+1"] as const;

export function TermStructureChart({ data }: { data: TermStructureRow[] }) {
  if (data.length < 2) {
    return (
      <AnalyticalSeriesPanel title="Term Structure" subtitle="IV by DTE">
        <div style={{ color: "var(--text-muted)", fontSize: 11 }}>
          Insufficient expiries (need ≥2)
        </div>
      </AnalyticalSeriesPanel>
    );
  }
  const dtes = data.map((r) =>
    typeof r.dte === "number" && Number.isFinite(r.dte) ? r.dte : 0,
  );
  const allIvs: number[] = [];
  for (const row of data) {
    for (const key of ORDERED_STRIKES) {
      const v = toNum(row.by_strike[key]);
      if (v != null) allIvs.push(v);
    }
  }
  const domain = finiteDomain(allIvs);
  if (!domain) {
    return (
      <AnalyticalSeriesPanel title="Term Structure" subtitle="IV by DTE">
        <div style={{ color: "var(--text-muted)", fontSize: 11 }}>
          Insufficient finite IV data
        </div>
      </AnalyticalSeriesPanel>
    );
  }
  const W = 400;
  const H = 220;
  const M = { top: 8, right: 16, bottom: 24, left: 36 };
  const xDomain: [number, number] = [Math.min(...dtes), Math.max(...dtes) || 1];
  const x = linearScale(xDomain, [M.left, W - M.right]);
  const y = linearScale([domain.lo, domain.hi], [H - M.bottom, M.top]);

  return (
    <AnalyticalSeriesPanel title="Term Structure" subtitle="IV by DTE">
      <div style={{ display: "flex", gap: 12, fontSize: 10, marginBottom: 4 }}>
        {ORDERED_STRIKES.map((k) => (
          <span key={k} style={{ color: STRIKE_COLORS[k] }}>
            — {k}
          </span>
        ))}
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} role="img">
        {ORDERED_STRIKES.map((label) => {
          const pts: Point[] = data
            .map((row, i) => {
              const v = toNum(row.by_strike[label]);
              return v == null ? null : ([x(dtes[i]), y(v)] as Point);
            })
            .filter((p): p is Point => p !== null);
          return (
            <path
              key={label}
              d={pathFromPoints(pts)}
              stroke={STRIKE_COLORS[label]}
              fill="none"
              strokeWidth={1.5}
            />
          );
        })}
        <text
          x={M.left - 4}
          y={H - M.bottom}
          fontSize={9}
          textAnchor="end"
          fill="var(--text-muted)"
        >
          {(domain.lo * 100).toFixed(1)}%
        </text>
        <text
          x={M.left - 4}
          y={M.top + 8}
          fontSize={9}
          textAnchor="end"
          fill="var(--text-muted)"
        >
          {(domain.hi * 100).toFixed(1)}%
        </text>
        <text x={M.left} y={H - 4} fontSize={9} fill="var(--text-muted)">
          {xDomain[0]}d
        </text>
        <text
          x={W - M.right}
          y={H - 4}
          fontSize={9}
          textAnchor="end"
          fill="var(--text-muted)"
        >
          {xDomain[1]}d
        </text>
      </svg>
    </AnalyticalSeriesPanel>
  );
}
