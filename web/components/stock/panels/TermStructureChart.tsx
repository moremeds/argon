import { toNum } from "@/lib/formatters";
import { chartFrame, finiteDomain, pathFromPoints } from "@/lib/svgChart";
import type { Point } from "@/lib/svgChart";
import { FrameLabels } from "@/components/shared/FrameLabels";
import { AnalyticalSeriesPanel } from "./AnalyticalSeriesPanel";

export type TermStructureRow = {
  expiry: string;
  dte?: number | null;
  by_strike: Record<string, string | number | null>;
  strikes?: Record<string, string | number | null>;
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
  const frame = chartFrame();
  const xDomain: [number, number] = [Math.min(...dtes), Math.max(...dtes) || 1];
  const x = frame.x(xDomain);
  const y = frame.y([domain.lo, domain.hi]);

  return (
    <AnalyticalSeriesPanel title="Term Structure" subtitle="IV by DTE">
      <div style={{ display: "flex", gap: 12, fontSize: 10, marginBottom: 4 }}>
        {ORDERED_STRIKES.map((k) => {
          const s = toNum(data[0]?.strikes?.[k]);
          return (
            <span key={k} style={{ color: STRIKE_COLORS[k] }}>
              — {k}
              {s != null ? ` ($${s.toFixed(2)})` : ""}
            </span>
          );
        })}
      </div>
      <svg {...frame.svg}>
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
        <FrameLabels
          frame={frame}
          yLo={<>{(domain.lo * 100).toFixed(1)}%</>}
          yHi={<>{(domain.hi * 100).toFixed(1)}%</>}
          xFirst={<>{xDomain[0]}d</>}
          xLast={<>{xDomain[1]}d</>}
        />
      </svg>
    </AnalyticalSeriesPanel>
  );
}
