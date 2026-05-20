import { finiteDomain, linearScale, pathFromPoints } from "@/lib/svgChart";
import { AnalyticalSeriesPanel } from "./AnalyticalSeriesPanel";

type Series = {
  label: string;
  values: Array<number | null>;
  color: string;
};

type Props = {
  title: string;
  primary: Series;
  secondary: Series;
  dates: string[];
  markers?: string[];
};

const WIDTH = 560;
const HEIGHT = 220;
const PAD = { top: 16, right: 36, bottom: 26, left: 40 };

export function FlowTimelinePanel({
  title,
  primary,
  secondary,
  dates,
  markers = [],
}: Props) {
  const innerW = WIDTH - PAD.left - PAD.right;
  const innerH = HEIGHT - PAD.top - PAD.bottom;

  // finiteDomain returns {lo, hi, count} | null — bail out on insufficient data.
  const primaryDom = finiteDomain(primary.values);
  const secondaryDom = finiteDomain(secondary.values);
  if (!primaryDom || !secondaryDom) {
    return (
      <AnalyticalSeriesPanel title={title} subtitle="NO DATA">
        <div
          style={{
            fontFamily: "var(--font-mono)",
            color: "var(--text-muted)",
            fontSize: 11,
          }}
        >
          NO DATA
        </div>
      </AnalyticalSeriesPanel>
    );
  }

  const x = linearScale(
    [0, Math.max(dates.length - 1, 1)],
    [PAD.left, PAD.left + innerW],
  );
  const yLeft = linearScale(
    [primaryDom.lo, primaryDom.hi],
    [PAD.top + innerH, PAD.top],
  );
  const yRight = linearScale(
    [secondaryDom.lo, secondaryDom.hi],
    [PAD.top + innerH, PAD.top],
  );

  const primaryPath = pathFromPoints(
    primary.values
      .map((v, i) =>
        v == null ? null : ([x(i), yLeft(v)] as [number, number]),
      )
      .filter((p): p is [number, number] => p !== null),
  );
  const secondaryPath = pathFromPoints(
    secondary.values
      .map((v, i) =>
        v == null ? null : ([x(i), yRight(v)] as [number, number]),
      )
      .filter((p): p is [number, number] => p !== null),
  );

  const dateIndex = new Map(dates.map((d, i) => [d, i]));

  return (
    <AnalyticalSeriesPanel title={title}>
      <Legend primary={primary} secondary={secondary} />
      <svg
        role="img"
        aria-label={`${title} timeline`}
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        style={{ width: "100%", height: "auto" }}
      >
        <title>{`${title}: ${primary.label} (left axis), ${secondary.label} (right axis)`}</title>

        {markers.map((m) => {
          const i = dateIndex.get(m);
          if (i == null) return null;
          return (
            <line
              key={m}
              data-testid="earnings-marker"
              x1={x(i)}
              x2={x(i)}
              y1={PAD.top}
              y2={PAD.top + innerH}
              stroke="var(--warning)"
              strokeDasharray="3 3"
              strokeOpacity={0.6}
            />
          );
        })}

        <path
          d={primaryPath}
          fill="none"
          stroke={primary.color}
          strokeWidth={1.5}
        />
        <path
          d={secondaryPath}
          fill="none"
          stroke={secondary.color}
          strokeWidth={1.5}
        />
      </svg>
    </AnalyticalSeriesPanel>
  );
}

function Legend({ primary, secondary }: { primary: Series; secondary: Series }) {
  return (
    <div
      role="list"
      aria-label="Series legend"
      style={{
        display: "flex",
        gap: 14,
        marginBottom: 6,
        fontFamily: "var(--font-mono)",
        fontSize: 10,
        letterSpacing: 1.5,
        textTransform: "uppercase",
        color: "var(--text-muted)",
      }}
    >
      <LegendItem color={primary.color} label={primary.label} axis="left" />
      <LegendItem color={secondary.color} label={secondary.label} axis="right" />
    </div>
  );
}

function LegendItem({
  color,
  label,
  axis,
}: {
  color: string;
  label: string;
  axis: "left" | "right";
}) {
  return (
    <div
      role="listitem"
      style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
    >
      <span
        aria-hidden
        style={{
          display: "inline-block",
          width: 14,
          height: 2,
          background: color,
        }}
      />
      <span>
        {label} <span style={{ opacity: 0.65 }}>({axis})</span>
      </span>
    </div>
  );
}
