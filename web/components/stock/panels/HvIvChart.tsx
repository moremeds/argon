import { toNum } from "@/lib/formatters";
import { chartFrame, finiteDomain, pathFromPoints } from "@/lib/svgChart";
import type { Point } from "@/lib/svgChart";
import { FrameLabels } from "@/components/shared/FrameLabels";
import { AnalyticalSeriesPanel } from "./AnalyticalSeriesPanel";

export type HvIvPoint = {
  date: string;
  iv?: string | number | null | undefined;
  rv?: string | number | null | undefined;
};

export function HvIvChart({ data }: { data: HvIvPoint[] }) {
  if (data.length < 2) {
    return (
      <AnalyticalSeriesPanel
        title="HV / IV"
        subtitle="IV (fwd ~30d) vs RV (trailing 21d) — lag is the VRP"
      >
        <div style={{ color: "var(--text-muted)", fontSize: 11 }}>
          Insufficient history (need ≥2d, have {data.length}d)
        </div>
      </AnalyticalSeriesPanel>
    );
  }
  const frame = chartFrame();
  const ivs = data.map((d) => toNum(d.iv));
  const rvs = data.map((d) => toNum(d.rv));
  const domain = finiteDomain([...ivs, ...rvs]);
  if (!domain) {
    return (
      <AnalyticalSeriesPanel
        title="HV / IV"
        subtitle="IV (fwd ~30d) vs RV (trailing 21d) — lag is the VRP"
      >
        <div style={{ color: "var(--text-muted)", fontSize: 11 }}>
          Insufficient finite history
        </div>
      </AnalyticalSeriesPanel>
    );
  }
  const { lo, hi } = domain;
  const x = frame.x([0, data.length - 1]);
  const y = frame.y([lo, hi]);
  const ivPath = pathFromPoints(
    ivs
      .map((v, i) => [x(i), v == null ? NaN : y(v)] as Point)
      .filter(([, vy]) => Number.isFinite(vy)),
  );
  const rvPath = pathFromPoints(
    rvs
      .map((v, i) => [x(i), v == null ? NaN : y(v)] as Point)
      .filter(([, vy]) => Number.isFinite(vy)),
  );
  return (
    <AnalyticalSeriesPanel
      title="HV / IV"
      subtitle="IV (fwd ~30d) vs RV (trailing 21d) — lag is the VRP"
    >
      <div style={{ display: "flex", gap: 12, fontSize: 10, marginBottom: 4 }}>
        <span style={{ color: "var(--accent-bg)" }}>— IV</span>
        <span style={{ color: "var(--accent-warm)" }}>— RV</span>
      </div>
      <svg {...frame.svg}>
        <path
          d={ivPath}
          stroke="var(--accent-bg)"
          fill="none"
          strokeWidth={1.5}
        />
        <path
          d={rvPath}
          stroke="var(--accent-warm)"
          fill="none"
          strokeWidth={1.5}
        />
        <FrameLabels
          frame={frame}
          yLo={<>{(lo * 100).toFixed(1)}%</>}
          yHi={<>{(hi * 100).toFixed(1)}%</>}
          xFirst={data[0].date}
          xLast={data[data.length - 1].date}
        />
      </svg>
    </AnalyticalSeriesPanel>
  );
}
