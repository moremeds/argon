import { BoardRead } from "@/components/macro/domain/BoardPanel";
import { humanizeText } from "@/components/macro/presentation";

import { fmtValue, toFiniteNumber } from "./format";
import { isWithheld, releaseDate } from "./policyPath";
import type { PolicyComparison, PolicyPathSlot } from "./types";

// The Regime-width macro canvas gives each half-width panel about 620px of SVG
// room after panel/chart padding. Keeping the artifact's 560-unit frame here
// magnifies every label by 11%; use the available width as the coordinate frame
// so chart typography stays on the desk's 1:1 scale.
const WIDTH = 620;
const HEIGHT = 190;
const X0 = 120;
const X1 = 580;

const LANES: Array<{
  kind: PolicyPathSlot["kind"];
  label: string;
  color: string;
}> = [
  { kind: "actual", label: "Actual (FOMC)", color: "var(--text-primary)" },
  {
    kind: "dealer_expectations",
    label: "Dealer (NY Fed SME)",
    color: "var(--accent-cool)",
  },
  {
    kind: "committee_projection",
    label: "SEP median",
    color: "var(--info)",
  },
  {
    kind: "market_implied",
    label: "Market-implied",
    color: "var(--warning)",
  },
];

function pointFor(slot: PolicyPathSlot | null | undefined) {
  const path = slot?.path;
  if (!path || isWithheld(path)) return null;
  const point = path.points?.[0];
  const value = toFiniteNumber(point?.rate_percent, Number.NaN);
  return point && Number.isFinite(value) ? { path, point, value } : null;
}

function laneDetail(slot: PolicyPathSlot | null | undefined): string {
  const path = slot?.path;
  if (!path) {
    return slot?.missing_reason ?? "This publisher lane is unavailable.";
  }
  if (isWithheld(path)) {
    return `Rejected: ${path.source_kind} is not publisher evidence; its numbers are withheld.`;
  }
  const point = path.points?.[0];
  const vote = point?.vote_split
    ? point.voter_names_stated === false && !(point.voted_against ?? []).length
      ? `Vote ${point.vote_split}; no dissenter named because the publisher printed no roster.`
      : `Vote ${point.vote_split}`
    : "";
  const range =
    point?.target_range_lower_percent != null &&
    point.target_range_upper_percent != null
      ? `${toFiniteNumber(point.target_range_lower_percent).toFixed(2)}–${toFiniteNumber(point.target_range_upper_percent).toFixed(2)}%`
      : "";
  const discovered = slot?.freshness.releases_discovered ?? 0;
  const freshness = `${slot?.freshness.status ?? "unknown"}${
    discovered > 0
      ? ` · ${slot?.freshness.releases_succeeded ?? 0}/${discovered} releases parsed`
      : ""
  }`;
  const anonymity =
    path.kind === "committee_projection" ? "SEP dots are anonymous" : "";
  return humanizeText([
    path.source,
    `released ${releaseDate(path)}`,
    range,
    point?.action,
    vote,
    anonymity,
    freshness,
  ]
    .filter(Boolean)
    .join(" · "));
}

function chartDomain(values: number[]): { min: number; max: number } {
  if (!values.length) return { min: 3.5, max: 4 };
  const min = Math.floor((Math.min(...values) - 0.125) * 8) / 8;
  const max = Math.ceil((Math.max(...values) + 0.125) * 8) / 8;
  return max > min ? { min, max } : { min: min - 0.25, max: max + 0.25 };
}

export function PolicyPathComparison({
  comparison,
  errorMessage,
}: {
  comparison: PolicyComparison | null | undefined;
  errorMessage?: string;
}) {
  if (!comparison) {
    return (
      <div className="note-refuse" data-testid="policy-paths-missing">
        <b>HONEST BOUNDARY</b>{" "}
        {errorMessage ?? "No policy comparison has been assembled for this instant."}
      </div>
    );
  }

  const slots: Record<string, PolicyPathSlot | null | undefined> = {
    actual: comparison.actual,
    dealer_expectations: comparison.dealer_expectations,
    committee_projection: comparison.committee_projection,
    market_implied: comparison.market_implied,
  };
  const lanes = LANES.map((lane, index) => ({
    ...lane,
    index,
    slot: slots[lane.kind],
    reading: pointFor(slots[lane.kind]),
  }));
  const values = lanes.flatMap((lane) =>
    lane.reading ? [lane.reading.value] : [],
  );
  const { min, max } = chartDomain(values);
  const xFor = (value: number) => X0 + ((value - min) / (max - min)) * (X1 - X0);
  const ticks = Array.from({ length: 5 }, (_, index) =>
    min + ((max - min) * index) / 4,
  );
  const actual = lanes.find((lane) => lane.kind === "actual")?.reading?.value;
  const availableForward = lanes.filter(
    (lane) => lane.kind !== "actual" && lane.reading,
  );
  const widestSpread =
    actual == null || !availableForward.length
      ? null
      : Math.max(
          ...availableForward.map((lane) =>
            Math.abs((lane.reading!.value - actual) * 100),
          ),
        );
  const direction =
    actual == null || !availableForward.length
      ? "Need the actual rate and one forward path to compare."
      : availableForward.every((lane) => lane.reading!.value >= actual)
        ? "All available forward paths are at or above the current rate; they disagree on level."
        : availableForward.every((lane) => lane.reading!.value <= actual)
          ? "All available forward paths are at or below the current rate; they disagree on level."
          : "Forward paths straddle the current rate; level and direction both differ."

  return (
    <>
      <div className="chart" data-testid="policy-path-comparison">
        <svg
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          role="img"
          aria-label="Four separately published policy paths compared without averaging"
        >
          {ticks.map((tick) => {
            const x = xFor(tick);
            return (
              <g key={tick}>
                <line x1={x} y1="20" x2={x} y2="160" stroke="var(--border-dim)" />
                <text x={x} y="176" textAnchor="middle" fill="var(--text-secondary)" fontSize="10">
                  {tick.toFixed(3)}{tick === ticks.at(-1) ? "%" : ""}
                </text>
              </g>
            );
          })}
          {lanes.map((lane) => {
            const y = 35 + lane.index * 35;
            const reading = lane.reading;
            const path = lane.slot?.path;
            const pathStatus = !path
              ? "unavailable"
              : isWithheld(path)
                ? "rejected"
                : "available";
            return (
              <g
                key={lane.kind}
                data-testid={`policy-path-lane-${lane.kind}`}
                data-path-status={pathStatus}
              >
                <title>{laneDetail(lane.slot)}</title>
                <text x="8" y={y + 4} fill="var(--text-secondary)" fontSize="10">
                  {lane.label}
                </text>
                <line x1={X0} y1={y} x2={X1} y2={y} stroke="var(--border-dim)" strokeDasharray="2 3" />
                {reading ? (
                  <>
                    <circle cx={xFor(reading.value)} cy={y} r="6" fill={lane.color} stroke="var(--bg-base)" strokeWidth="2">
                      <title>{`${lane.label} ${reading.value.toFixed(3)}% · released ${releaseDate(reading.path)}`}</title>
                    </circle>
                    <text x={Math.min(xFor(reading.value) + 12, 482)} y={y + 4} fill="var(--text-primary)" fontSize="11" fontWeight="600">
                      {reading.value.toFixed(3)}
                      {actual != null && lane.kind !== "actual" ? (
                        <tspan fill="var(--text-secondary)" fontWeight="400">
                          {` ${reading.value >= actual ? "+" : ""}${((reading.value - actual) * 100).toFixed(1)}bp`}
                        </tspan>
                      ) : null}
                    </text>
                  </>
                ) : (
                  <text x={X0 + 8} y={y + 4} fill="var(--text-muted)" fontSize="10">
                    {pathStatus === "rejected"
                      ? laneDetail(lane.slot)
                      : humanizeText(lane.slot?.missing_reason ?? "unavailable")}
                  </text>
                )}
              </g>
            );
          })}
        </svg>
        <div className="cap">
          Levels are publisher values <span className="tag real">REAL</span>
          {widestSpread != null ? (
            <> · spreads versus actual and widest spread {fmtValue(widestSpread, "bps", 1)} <span className="tag comp">COMPUTED</span></>
          ) : null}
          {" · "}four lanes, never averaged ·{" "}
          <span data-testid="sep-anonymity-note">SEP dots are anonymous</span>
        </div>
      </div>
      <BoardRead>
        {direction} <b>The four paths remain separate and are never averaged.</b>
      </BoardRead>
    </>
  );
}
