"use client";

import {
  finiteDomain,
  linearScale,
  niceTicks,
  pathFromNullablePoints,
} from "@/lib/svgChart";
import type {
  GexIntradayData,
  GexIntradayPoint,
  GexIntradaySession,
} from "@/lib/regime/useGexIntraday";

const WIDTH = 880;
const HEIGHT = 280;
const PAD = { top: 16, right: 72, bottom: 38, left: 64 };

const COLORS = {
  spot: "var(--text-primary)",
  flip: "var(--accent-warm, #F5A623)",
  netGex: "var(--accent-bg, #05AD98)",
  iv: "var(--extreme, #D946A8)",
  divider: "var(--border-dim)",
  grid: "rgba(148,163,184,0.08)",
  zero: "var(--border-dim)",
  // Subtle alternating fill behind every other session column. The shade
  // separates adjacent ET dates without competing with the four series.
  sessionBand: "rgba(148,163,184,0.05)",
};

const ET_TZ = "America/New_York";

/** "YYYY-MM-DD" ET → ET noon ISO so callers don't need to parse twice. */
function etDateLabel(d: string): string {
  // d is already a YYYY-MM-DD string from the API; show month+day only.
  const [, m, day] = d.split("-");
  return `${m}/${day}`;
}

/** ET time-of-day in minutes from midnight, derived from an ISO timestamp. */
function etMinutes(ts: string): number {
  const date = new Date(ts);
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: ET_TZ,
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(date);
  const h = Number(parts.find((p) => p.type === "hour")?.value ?? 0);
  const min = Number(parts.find((p) => p.type === "minute")?.value ?? 0);
  return h * 60 + min;
}

type Flat = {
  x: number; // index across the concatenated session timeline
  spot: number | null;
  flip: number | null;
  netGex: number | null;
  iv: number | null;
};

/** Concatenate sessions into a single index space, also remembering the
 * index range covered by each session for date dividers + tick labels. */
function flatten(sessions: GexIntradaySession[]): {
  flat: Flat[];
  sessionRanges: {
    et_date: string;
    start: number;
    end: number;
    points: GexIntradayPoint[];
  }[];
} {
  const flat: Flat[] = [];
  const ranges: {
    et_date: string;
    start: number;
    end: number;
    points: GexIntradayPoint[];
  }[] = [];
  for (const s of sessions) {
    if (!s.points.length) continue;
    const start = flat.length;
    for (const p of s.points) {
      flat.push({
        x: flat.length,
        spot: p.spot,
        flip: p.gex_flip,
        netGex: p.net_gex,
        iv: p.iv30d,
      });
    }
    ranges.push({
      et_date: s.et_date,
      start,
      end: flat.length - 1,
      points: s.points,
    });
  }
  return { flat, sessionRanges: ranges };
}

/** Tick-mark indices inside a session at 9:30, 12:00, 16:00 ET (when
 * those minutes are present in the session's point list). */
function rthTicksForSession(points: GexIntradayPoint[]): {
  idx: number;
  label: string;
}[] {
  const targets: [number, string][] = [
    [9 * 60 + 30, "09:30"],
    [12 * 60, "12:00"],
    [16 * 60, "16:00"],
  ];
  const out: { idx: number; label: string }[] = [];
  for (const [target, label] of targets) {
    let bestIdx = -1;
    let bestDelta = Infinity;
    for (let i = 0; i < points.length; i++) {
      const d = Math.abs(etMinutes(points[i].ts) - target);
      if (d < bestDelta) {
        bestDelta = d;
        bestIdx = i;
      }
    }
    // Skip the tick when the closest point is > 15 min away (e.g. partial
    // session, or session that doesn't reach the close).
    if (bestIdx >= 0 && bestDelta <= 15) out.push({ idx: bestIdx, label });
  }
  return out;
}

function LegendSwatch({
  color,
  label,
  dashed,
}: {
  color: string;
  label: string;
  dashed?: boolean;
}) {
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        fontFamily: "var(--font-mono)",
        fontSize: 10,
        letterSpacing: "0.06em",
        color: "var(--text-secondary)",
      }}
    >
      <svg width="20" height="6" aria-hidden="true">
        <line
          x1={0}
          x2={20}
          y1={3}
          y2={3}
          stroke={color}
          strokeWidth={2}
          strokeDasharray={dashed ? "3 2" : undefined}
        />
      </svg>
      {label}
    </span>
  );
}

export function GexIntradayChart({
  data,
  ticker,
}: {
  data: GexIntradayData | null;
  ticker: string;
}) {
  if (!data || !data.sessions.length) {
    return (
      <div className="section" data-testid="gex-intraday-empty">
        <div className="section-header">
          <div className="section-title">{ticker} — Intraday GEX (RTH)</div>
        </div>
        <div
          className="section-body"
          style={{
            padding: 24,
            textAlign: "center",
            color: "var(--text-muted)",
            fontFamily: "var(--font-mono)",
            fontSize: 11,
          }}
        >
          No intraday GEX snapshots available.
        </div>
      </div>
    );
  }

  const { flat, sessionRanges } = flatten(data.sessions);
  if (flat.length < 2) {
    return (
      <div className="section" data-testid="gex-intraday-thin">
        <div className="section-header">
          <div className="section-title">{ticker} — Intraday GEX (RTH)</div>
        </div>
        <div
          className="section-body"
          style={{
            padding: 24,
            textAlign: "center",
            color: "var(--text-muted)",
            fontFamily: "var(--font-mono)",
            fontSize: 11,
          }}
        >
          Only {flat.length} intraday tick available — chart needs at least 2.
        </div>
      </div>
    );
  }

  const xScale = linearScale(
    [0, flat.length - 1],
    [PAD.left, WIDTH - PAD.right],
  );

  // Two y-axes:
  //   left  = net GEX ($), often crosses zero
  //   right = price band (SPX spot + flip strike share the same scale) and
  //           IV30D as a percent (rescaled into the same band).
  const netGexD = finiteDomain(flat.map((p) => p.netGex));
  const priceD = finiteDomain(flat.flatMap((p) => [p.spot, p.flip]));
  const ivD = finiteDomain(flat.map((p) => p.iv));

  const yLeft = netGexD
    ? linearScale([netGexD.lo, netGexD.hi], [HEIGHT - PAD.bottom, PAD.top])
    : null;
  const yRight = priceD
    ? linearScale([priceD.lo, priceD.hi], [HEIGHT - PAD.bottom, PAD.top])
    : null;
  // IV30D rescaled into the right-axis band so all four series share one viewport.
  const yIv = ivD
    ? linearScale([ivD.lo, ivD.hi], [HEIGHT - PAD.bottom, PAD.top])
    : null;

  function pathFor(
    accessor: (p: Flat) => number | null,
    scale: ((v: number) => number) | null,
  ): string {
    if (scale == null) return "";
    // Build a separate sub-path PER SESSION and concatenate. This breaks
    // every series at the session boundary so a line from session N's
    // 16:00 ET close never crosses to session N+1's 09:30 ET open
    // (overnight RTH motion that did not happen). pathFromNullablePoints
    // also handles intra-session gaps + isolated singletons within each
    // session — see svgChart.ts.
    return sessionRanges
      .map((s) =>
        pathFromNullablePoints(
          flat.slice(s.start, s.end + 1).map((p): [number, number] | null => {
            const v = accessor(p);
            return v == null ? null : [xScale(p.x), scale(v)];
          }),
        ),
      )
      .filter((sub) => sub.length > 0)
      .join(" ");
  }

  const netGexPath = pathFor((p) => p.netGex, yLeft);
  const flipPath = pathFor((p) => p.flip, yRight);
  const spotPath = pathFor((p) => p.spot, yRight);
  const ivPath = pathFor((p) => p.iv, yIv);

  // Y-axis ticks for the left scale (net GEX).
  const leftTicks = netGexD ? niceTicks(netGexD.lo, netGexD.hi, 4) : [];
  // Y-axis ticks for the right scale (price band).
  const rightTicks = priceD ? niceTicks(priceD.lo, priceD.hi, 4) : [];

  return (
    <div className="section" data-testid="gex-intraday-chart">
      <div className="section-header">
        <div className="section-title">
          {ticker} — Intraday GEX, last {sessionRanges.length} sessions (RTH)
        </div>
        <div
          style={{
            display: "flex",
            gap: 14,
            flexWrap: "wrap",
            alignItems: "center",
          }}
        >
          <LegendSwatch color={COLORS.spot} label="SPOT" />
          <LegendSwatch color={COLORS.flip} label="GEX FLIP" dashed />
          <LegendSwatch color={COLORS.netGex} label="NET GEX" />
          <LegendSwatch color={COLORS.iv} label="IV 30D" />
        </div>
      </div>
      <div className="section-body" style={{ padding: "8px 12px 12px" }}>
        <svg
          role="img"
          aria-label={`${ticker} intraday GEX, last ${sessionRanges.length} RTH sessions`}
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          style={{ width: "100%", height: HEIGHT, display: "block" }}
        >
          <title>{`${ticker} intraday — spot, flip, net GEX, IV30d`}</title>

          {/* Alternating session bands. Rendered first so every other ET
              date column reads as a subtly-different background — replaces
              what the colliding 09:30/16:00 boundary labels were trying to
              communicate. */}
          {sessionRanges.map((s, i) =>
            i % 2 === 1 ? (
              <rect
                key={`band-${s.et_date}`}
                x={xScale(s.start)}
                y={PAD.top}
                width={xScale(s.end) - xScale(s.start)}
                height={HEIGHT - PAD.top - PAD.bottom}
                fill={COLORS.sessionBand}
              />
            ) : null,
          )}

          {/* Zero line for net GEX (only when the scale crosses zero). */}
          {yLeft && netGexD && netGexD.lo <= 0 && netGexD.hi >= 0 && (
            <line
              x1={PAD.left}
              x2={WIDTH - PAD.right}
              y1={yLeft(0)}
              y2={yLeft(0)}
              stroke={COLORS.zero}
              strokeDasharray="2 3"
            />
          )}

          {/* Session dividers + date labels along the bottom. */}
          {sessionRanges.map((s, i) => {
            const xStart = xScale(s.start);
            const xEnd = xScale(s.end);
            const midX = (xStart + xEnd) / 2;
            const showDivider = i > 0;
            return (
              <g key={s.et_date}>
                {showDivider && (
                  <line
                    x1={xStart}
                    x2={xStart}
                    y1={PAD.top}
                    y2={HEIGHT - PAD.bottom}
                    stroke={COLORS.divider}
                    strokeWidth={1}
                  />
                )}
                {/* Date label */}
                <text
                  x={midX}
                  y={HEIGHT - 6}
                  textAnchor="middle"
                  fontSize={10}
                  fontFamily="var(--font-mono)"
                  fill="var(--text-secondary)"
                  letterSpacing="0.06em"
                >
                  {etDateLabel(s.et_date)}
                </text>
                {/* RTH intraday ticks. Only the 12:00 anchor carries a
                    label — 09:30 and 16:00 sit at the session band edges
                    where adjacent-session labels used to collide; the band
                    edges themselves now communicate open/close. */}
                {rthTicksForSession(s.points).map((t) => {
                  const tx = xScale(s.start + t.idx);
                  const labeled = t.label === "12:00";
                  return (
                    <g key={`${s.et_date}-${t.label}`}>
                      <line
                        x1={tx}
                        x2={tx}
                        y1={HEIGHT - PAD.bottom}
                        y2={HEIGHT - PAD.bottom + (labeled ? 4 : 2)}
                        stroke="var(--text-muted)"
                        opacity={labeled ? 1 : 0.5}
                      />
                      {labeled && (
                        <text
                          x={tx}
                          y={HEIGHT - PAD.bottom + 14}
                          textAnchor="middle"
                          fontSize={8}
                          fontFamily="var(--font-mono)"
                          fill="var(--text-muted)"
                        >
                          {t.label}
                        </text>
                      )}
                    </g>
                  );
                })}
              </g>
            );
          })}

          {/* Y-axis tick labels. niceTicks may extend beyond the data
              domain (e.g. an upper tick of +100K when data peaks at +95K);
              clamp the label y so it always renders inside the SVG viewBox
              and only draw the gridline when its y falls inside the chart
              canvas. Same fix the daily HistoryChart got. */}
          {yLeft &&
            leftTicks.map((v) => {
              const y = yLeft(v);
              const labelY = Math.max(
                PAD.top + 10,
                Math.min(HEIGHT - PAD.bottom - 4, y + 3),
              );
              const lineInside = y >= PAD.top && y <= HEIGHT - PAD.bottom;
              return (
                <g key={`L${v}`}>
                  {lineInside && (
                    <line
                      x1={PAD.left - 4}
                      x2={WIDTH - PAD.right}
                      y1={y}
                      y2={y}
                      stroke={COLORS.grid}
                    />
                  )}
                  <text
                    x={PAD.left - 6}
                    y={labelY}
                    textAnchor="end"
                    fontSize={9}
                    fontFamily="var(--font-mono)"
                    fill={COLORS.netGex}
                  >
                    {Math.abs(v) >= 1000
                      ? `${(v / 1000).toFixed(1)}K`
                      : v.toFixed(0)}
                  </text>
                </g>
              );
            })}

          {/* Right y-axis (price band: SPX + flip strike). */}
          {yRight &&
            rightTicks.map((v) => {
              const y = yRight(v);
              const labelY = Math.max(
                PAD.top + 10,
                Math.min(HEIGHT - PAD.bottom - 4, y + 3),
              );
              return (
                <g key={`R${v}`}>
                  <text
                    x={WIDTH - PAD.right + 6}
                    y={labelY}
                    textAnchor="start"
                    fontSize={9}
                    fontFamily="var(--font-mono)"
                    fill="var(--text-secondary)"
                  >
                    {v.toFixed(0)}
                  </text>
                </g>
              );
            })}

          {/* Series (draw net_gex first so price lines sit on top visually).
              `strokeLinecap="round"` is REQUIRED so the zero-length L emitted
              by pathFromNullablePoints for isolated points renders as a
              visible dot (diameter = strokeWidth). Critical for gex_flip,
              which the scanner emits as sparse single observations. */}
          <path
            d={netGexPath}
            fill="none"
            stroke={COLORS.netGex}
            strokeWidth={1.4}
            strokeLinecap="round"
          />
          <path
            d={flipPath}
            fill="none"
            stroke={COLORS.flip}
            strokeWidth={1.6}
            strokeDasharray="3 2"
            strokeLinecap="round"
          />
          <path
            d={spotPath}
            fill="none"
            stroke={COLORS.spot}
            strokeWidth={1.4}
            strokeLinecap="round"
          />
          <path
            d={ivPath}
            fill="none"
            stroke={COLORS.iv}
            strokeWidth={1.1}
            opacity={0.7}
            strokeLinecap="round"
          />
        </svg>
      </div>
    </div>
  );
}
