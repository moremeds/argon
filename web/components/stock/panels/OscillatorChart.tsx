import {
  finiteDomain,
  linearScale,
  niceTicks,
  pathFromNullablePoints,
} from "@/lib/svgChart";
import { AnalyticalSeriesPanel } from "./AnalyticalSeriesPanel";
import { ChartDateAxis } from "./ChartDateAxis";

// Shared geometry — EVERY stacked technicals chart (anchor + oscillators) uses
// these so a given date sits at the same pixel column across the whole stack,
// making the panels vertically alignable against price.
export const CW = 900;
export const CPAD = { l: 46, r: 16, t: 12, b: 22 };
export const xScaleFor = (n: number) =>
  linearScale([0, Math.max(1, n - 1)], [CPAD.l, CW - CPAD.r]);

export type ChartLine = {
  values: Array<number | null>;
  color: string;
  label?: string;
  strokeWidth?: number;
  opacity?: number;
};
type RefLine = { y: number; label?: string; solid?: boolean };
type Zone = { from: number; to: number; color: string };

function fmtTick(v: number): string {
  const a = Math.abs(v);
  if (a === 0) return "0";
  if (a >= 100) return v.toFixed(0);
  if (a >= 10) return v.toFixed(1);
  if (a >= 1) return v.toFixed(2);
  return v.toFixed(3);
}

export function OscillatorChart({
  title,
  subtitle,
  headline,
  explanation,
  dates,
  lines = [],
  histogram,
  histogramOverlay,
  height = 160,
  yDomain,
  unit = "",
  refLines = [],
  zones = [],
}: {
  title: string;
  subtitle?: string;
  headline?: string;
  explanation?: string;
  dates: Array<string | null | undefined>;
  lines?: ChartLine[];
  histogram?: { values: Array<number | null>; label?: string };
  histogramOverlay?: {
    values: Array<number | null>;
    color: string;
    label?: string;
  };
  height?: number;
  yDomain?: [number, number];
  unit?: string;
  refLines?: RefLine[];
  zones?: Zone[];
}) {
  const H = height;
  const n = dates.length;
  const allVals: Array<number | null> = [
    ...lines.flatMap((l) => l.values),
    ...(histogram?.values ?? []),
    ...(histogramOverlay?.values ?? []),
    ...refLines.map((r) => r.y),
  ];
  const auto = finiteDomain(allVals);
  const dom = yDomain ? { lo: yDomain[0], hi: yDomain[1] } : auto;
  if (!dom || n < 2) {
    return (
      <AnalyticalSeriesPanel title={title} subtitle={subtitle}>
        <div style={{ color: "var(--text-muted)", fontSize: 12 }}>
          Not enough history.
        </div>
      </AnalyticalSeriesPanel>
    );
  }
  const x = xScaleFor(n);
  const pad = yDomain ? 0 : (dom.hi - dom.lo) * 0.08 || 1;
  const y = linearScale([dom.lo - pad, dom.hi + pad], [H - CPAD.b, CPAD.t]);
  const ticks = niceTicks(dom.lo, dom.hi, 4);
  const barW = Math.max(1, ((CW - CPAD.l - CPAD.r) / Math.max(1, n)) * 0.85);

  return (
    <AnalyticalSeriesPanel
      title={title}
      subtitle={subtitle}
      headline={headline}
    >
      <svg
        viewBox={`0 0 ${CW} ${H}`}
        width="100%"
        role="img"
        style={{ display: "block" }}
      >
        <title>{title}</title>
        {zones.map((z, i) => (
          <rect
            key={`z${i}`}
            x={CPAD.l}
            y={y(z.to)}
            width={CW - CPAD.r - CPAD.l}
            height={Math.abs(y(z.from) - y(z.to))}
            fill={z.color}
            opacity={0.07}
          />
        ))}
        {ticks.map((t) => (
          <g key={`t${t}`}>
            <line
              x1={CPAD.l}
              x2={CW - CPAD.r}
              y1={y(t)}
              y2={y(t)}
              stroke="var(--border-dim)"
              strokeWidth={0.4}
              strokeDasharray="2 3"
            />
            <text
              x={CPAD.l - 6}
              y={y(t) + 3}
              fontSize={9}
              fill="var(--text-muted)"
              textAnchor="end"
              fontFamily="var(--font-mono)"
            >
              {fmtTick(t)}
              {unit}
            </text>
          </g>
        ))}
        {refLines.map((r, i) => (
          <g key={`r${i}`}>
            <line
              x1={CPAD.l}
              x2={CW - CPAD.r}
              y1={y(r.y)}
              y2={y(r.y)}
              stroke="var(--text-muted)"
              strokeWidth={r.solid ? 1 : 0.6}
              strokeDasharray={r.solid ? undefined : "4 3"}
              opacity={0.5}
            />
            {r.label && (
              <text
                x={CW - CPAD.r}
                y={y(r.y) - 2}
                fontSize={9}
                fill="var(--text-muted)"
                textAnchor="end"
                fontFamily="var(--font-mono)"
              >
                {r.label}
              </text>
            )}
          </g>
        ))}
        {histogramOverlay?.values.map((v, i) =>
          v == null ? null : (
            <rect
              key={`ho${i}`}
              x={x(i) - barW / 2}
              y={Math.min(y(0), y(v))}
              width={barW}
              height={Math.max(0.5, Math.abs(y(v) - y(0)))}
              fill={histogramOverlay.color}
              opacity={0.45}
            />
          ),
        )}
        {histogram?.values.map((v, i) =>
          v == null ? null : (
            // When a slow overlay sits behind it, draw the fast bars narrower
            // so "sharp fast vs wide slow" reads at a glance.
            <rect
              key={`h${i}`}
              x={x(i) - (histogramOverlay ? barW * 0.28 : barW / 2)}
              y={Math.min(y(0), y(v))}
              width={histogramOverlay ? barW * 0.56 : barW}
              height={Math.max(0.5, Math.abs(y(v) - y(0)))}
              fill={v >= 0 ? "var(--positive)" : "var(--negative)"}
              opacity={0.9}
            />
          ),
        )}
        {lines.map((l, li) => (
          <path
            key={`l${li}`}
            d={pathFromNullablePoints(
              l.values.map((v, i) =>
                v == null ? null : ([x(i), y(v)] as [number, number]),
              ),
            )}
            fill="none"
            stroke={l.color}
            strokeWidth={l.strokeWidth ?? 1.2}
            opacity={l.opacity ?? 1}
          />
        ))}
        <ChartDateAxis dates={dates} x={x} y={H - 5} />
      </svg>
      {(histogramOverlay?.label || histogram?.label) && (
        <div style={{ marginTop: 6, display: "flex", gap: 16 }}>
          {histogramOverlay?.label && (
            <span
              style={{ display: "inline-flex", alignItems: "center", gap: 5 }}
            >
              <span
                style={{
                  width: 14,
                  height: 9,
                  background: histogramOverlay.color,
                  opacity: 0.5,
                  display: "inline-block",
                  borderRadius: 1,
                }}
              />
              <span style={{ fontSize: 10, color: "var(--text-muted)" }}>
                {histogramOverlay.label}
              </span>
            </span>
          )}
          {histogram?.label && (
            <span
              style={{ display: "inline-flex", alignItems: "center", gap: 5 }}
            >
              {/* split swatch = the fast bars are green up / red down */}
              <span
                style={{ display: "inline-flex", width: 8, height: 9 }}
                aria-hidden
              >
                <span
                  style={{
                    flex: 1,
                    background: "var(--positive)",
                    opacity: 0.9,
                  }}
                />
                <span
                  style={{
                    flex: 1,
                    background: "var(--negative)",
                    opacity: 0.9,
                  }}
                />
              </span>
              <span style={{ fontSize: 10, color: "var(--text-muted)" }}>
                {histogram.label}
              </span>
            </span>
          )}
        </div>
      )}
      {lines.filter((l) => l.label).length > 1 && (
        <div style={{ marginTop: 6 }}>
          {lines.map((l, i) =>
            l.label ? (
              <span
                key={i}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 4,
                  marginRight: 12,
                }}
              >
                <span
                  style={{
                    width: 14,
                    height: Math.max(2, l.strokeWidth ?? 2),
                    background: l.color,
                    opacity: l.opacity ?? 1,
                    display: "inline-block",
                  }}
                />
                <span
                  style={{
                    fontSize: 10,
                    color: "var(--text-muted)",
                    opacity: l.opacity ?? 1,
                  }}
                >
                  {l.label}
                </span>
              </span>
            ) : null,
          )}
        </div>
      )}
      {explanation && (
        <div
          style={{
            fontSize: 11,
            color: "var(--text-muted)",
            marginTop: 8,
            lineHeight: 1.55,
          }}
        >
          {explanation}
        </div>
      )}
    </AnalyticalSeriesPanel>
  );
}
