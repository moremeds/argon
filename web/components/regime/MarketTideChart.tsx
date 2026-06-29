"use client";

import { finiteDomain, linearScale, niceTicks } from "@/lib/svgChart";
import type {
  MarketTideData,
  MarketTidePoint,
  MarketTideSession,
} from "@/lib/regime/useMarketTide";

const WIDTH = 880;
const HEIGHT = 320;
const PAD = { top: 16, right: 76, bottom: 38, left: 70 };
// Premium + spot share the top band; net volume gets the bottom band (UW layout).
const PREM_BOTTOM = 196;
const VOL_TOP = 222;
const VOL_BOTTOM = HEIGHT - PAD.bottom;

const COLORS = {
  call: "var(--positive, #22c55e)",
  put: "var(--negative, #ef4444)",
  spot: "var(--accent-warm, #F5A623)",
  vol: "var(--accent-vol, #38bdf8)",
  divider: "var(--border-dim)",
  grid: "rgba(148,163,184,0.08)",
  zero: "var(--border-dim)",
  sessionBand: "rgba(148,163,184,0.05)",
};

const ET_TZ = "America/New_York";
// ponytail: one formatter for the module lifetime — creating one per data point
// (7 k+ per render) causes measurable GC pressure; Intl.DateTimeFormat carries
// ICU locale data and timezone rule tables internally.
const _etFmt = new Intl.DateTimeFormat("en-US", {
  timeZone: ET_TZ,
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

function etDateLabel(d: string): string {
  const [, m, day] = d.split("-");
  return `${m}/${day}`;
}

/** ET time-of-day in minutes from midnight, from an ISO timestamp. */
function etMinutes(ts: string): number {
  const parts = _etFmt.formatToParts(new Date(ts));
  const h = Number(parts.find((p) => p.type === "hour")?.value ?? 0);
  const min = Number(parts.find((p) => p.type === "minute")?.value ?? 0);
  return h * 60 + min;
}

function fmtM(v: number): string {
  const m = v / 1_000_000;
  if (Math.abs(m) >= 1000) return `$${(m / 1000).toFixed(1)}B`;
  return `$${m.toFixed(0)}M`;
}

type Flat = {
  x: number;
  call: number | null;
  put: number | null;
  spot: number | null;
  vol: number | null;
};

function flatten(sessions: MarketTideSession[]): {
  flat: Flat[];
  sessionRanges: {
    date: string;
    start: number;
    end: number;
    points: MarketTidePoint[];
  }[];
} {
  const flat: Flat[] = [];
  const ranges: {
    date: string;
    start: number;
    end: number;
    points: MarketTidePoint[];
  }[] = [];
  for (const s of sessions) {
    if (!s.points.length) continue;
    const start = flat.length;
    for (const p of s.points) {
      flat.push({
        x: flat.length,
        call: p.net_call_premium,
        put: p.net_put_premium,
        spot: p.spot,
        vol: p.net_volume,
      });
    }
    ranges.push({
      date: s.date,
      start,
      end: flat.length - 1,
      points: s.points,
    });
  }
  return { flat, sessionRanges: ranges };
}

/** Closest point index to 09:30 / 12:00 / 16:00 ET within a session. */
function rthTicksForSession(points: MarketTidePoint[]): {
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
    if (bestIdx >= 0 && bestDelta <= 15) out.push({ idx: bestIdx, label });
  }
  return out;
}

function LegendSwatch({ color, label }: { color: string; label: string }) {
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
        <line x1={0} x2={20} y1={3} y2={3} stroke={color} strokeWidth={2} />
      </svg>
      {label}
    </span>
  );
}

function EmptyCard({ msg, testid }: { msg: string; testid: string }) {
  return (
    <div className="section" data-testid={testid}>
      <div className="section-header">
        <div className="section-title">Market Tide — Net Options Premium</div>
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
        {msg}
      </div>
    </div>
  );
}

export function MarketTideChart({ data }: { data: MarketTideData | null }) {
  if (!data || !data.sessions.length) {
    return (
      <EmptyCard
        msg="No market-tide snapshots available."
        testid="market-tide-empty"
      />
    );
  }

  const { flat, sessionRanges } = flatten(data.sessions);
  if (flat.length < 2) {
    return (
      <EmptyCard
        msg={`Only ${flat.length} tick available — chart needs at least 2.`}
        testid="market-tide-thin"
      />
    );
  }

  const spotTicker = data.spot_ticker ?? "SPY";
  const xScale = linearScale(
    [0, flat.length - 1],
    [PAD.left, WIDTH - PAD.right],
  );

  // Premium band: left $-axis (call + put net premium, crosses zero).
  const premD = finiteDomain(flat.flatMap((p) => [p.call, p.put]));
  const spotD = finiteDomain(flat.map((p) => p.spot));
  const volD = finiteDomain(flat.map((p) => p.vol));

  const yPrem = premD
    ? linearScale([premD.lo, premD.hi], [PREM_BOTTOM, PAD.top])
    : null;
  const ySpot = spotD
    ? linearScale([spotD.lo, spotD.hi], [PREM_BOTTOM, PAD.top])
    : null;
  // Net volume: zero-centered band at the bottom.
  const volMax = volD ? Math.max(Math.abs(volD.lo), Math.abs(volD.hi)) || 1 : 1;
  const yVol = linearScale([-volMax, volMax], [VOL_BOTTOM, VOL_TOP]);

  /** Per-session sub-paths concatenated so a line never crosses the overnight
   *  gap (mirrors GexIntradayChart.pathFor). */
  function pathFor(
    accessor: (p: Flat) => number | null,
    scale: ((v: number) => number) | null,
  ): string {
    if (scale == null) return "";
    return sessionRanges
      .map((s) => {
        const parts: string[] = [];
        let move = true;
        for (let i = s.start; i <= s.end; i++) {
          const v = accessor(flat[i]);
          if (v == null || !Number.isFinite(v)) {
            move = true;
            continue;
          }
          parts.push(`${move ? "M" : "L"}${xScale(flat[i].x)},${scale(v)}`);
          move = false;
        }
        return parts.join(" ");
      })
      .filter((sub) => sub.length > 0)
      .join(" ");
  }

  /** Volume filled area per session, anchored to the band's zero line. */
  function volAreaForSession(s: { start: number; end: number }): string {
    const pts: [number, number][] = [];
    for (let i = s.start; i <= s.end; i++) {
      const v = flat[i].vol;
      if (v == null || !Number.isFinite(v)) continue;
      pts.push([xScale(flat[i].x), yVol(v)]);
    }
    if (pts.length < 2) return "";
    const y0 = yVol(0);
    const body = pts.map(([x, y]) => `L${x},${y}`).join(" ");
    return `M${pts[0][0]},${y0} ${body} L${pts[pts.length - 1][0]},${y0} Z`;
  }

  const callPath = pathFor((p) => p.call, yPrem);
  const putPath = pathFor((p) => p.put, yPrem);
  const spotPath = pathFor((p) => p.spot, ySpot);

  const leftTicks = premD ? niceTicks(premD.lo, premD.hi, 4) : [];
  const rightTicks = spotD ? niceTicks(spotD.lo, spotD.hi, 4) : [];

  return (
    <div className="section" data-testid="market-tide-chart">
      <div className="section-header">
        <div className="section-title">
          Market Tide — Net Options Premium, last {sessionRanges.length}{" "}
          sessions
        </div>
        <div
          style={{
            display: "flex",
            gap: 14,
            flexWrap: "wrap",
            alignItems: "center",
          }}
        >
          <LegendSwatch color={COLORS.call} label="CALL PREM" />
          <LegendSwatch color={COLORS.put} label="PUT PREM" />
          <LegendSwatch color={COLORS.spot} label={spotTicker} />
          <LegendSwatch color={COLORS.vol} label="NET VOL" />
        </div>
      </div>
      <div className="section-body" style={{ padding: "8px 12px 12px" }}>
        <svg
          role="img"
          aria-label={`Market-wide net options premium, last ${sessionRanges.length} sessions`}
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          style={{ width: "100%", height: HEIGHT, display: "block" }}
        >
          <title>
            Market tide — net call/put premium, spot overlay, net volume
          </title>

          {/* Alternating session bands. */}
          {sessionRanges.map((s, i) =>
            i % 2 === 1 ? (
              <rect
                key={`band-${s.date}`}
                x={xScale(s.start)}
                y={PAD.top}
                width={xScale(s.end) - xScale(s.start)}
                height={VOL_BOTTOM - PAD.top}
                fill={COLORS.sessionBand}
              />
            ) : null,
          )}

          {/* Premium zero line. */}
          {yPrem && premD && premD.lo <= 0 && premD.hi >= 0 && (
            <line
              x1={PAD.left}
              x2={WIDTH - PAD.right}
              y1={yPrem(0)}
              y2={yPrem(0)}
              stroke={COLORS.zero}
              strokeDasharray="2 3"
            />
          )}
          {/* Volume zero line. */}
          <line
            x1={PAD.left}
            x2={WIDTH - PAD.right}
            y1={yVol(0)}
            y2={yVol(0)}
            stroke={COLORS.zero}
            strokeDasharray="2 3"
            opacity={0.6}
          />

          {/* Session dividers + date / RTH labels. */}
          {sessionRanges.map((s, i) => {
            const xStart = xScale(s.start);
            const xEnd = xScale(s.end);
            const midX = (xStart + xEnd) / 2;
            return (
              <g key={s.date}>
                {i > 0 && (
                  <line
                    x1={xStart}
                    x2={xStart}
                    y1={PAD.top}
                    y2={VOL_BOTTOM}
                    stroke={COLORS.divider}
                    strokeWidth={1}
                  />
                )}
                <text
                  x={midX}
                  y={HEIGHT - 6}
                  textAnchor="middle"
                  fontSize={10}
                  fontFamily="var(--font-mono)"
                  fill="var(--text-secondary)"
                  letterSpacing="0.06em"
                >
                  {etDateLabel(s.date)}
                </text>
                {rthTicksForSession(s.points).map((t) => {
                  const tx = xScale(s.start + t.idx);
                  const labeled = t.label === "12:00";
                  return (
                    <g key={`${s.date}-${t.label}`}>
                      <line
                        x1={tx}
                        x2={tx}
                        y1={VOL_BOTTOM}
                        y2={VOL_BOTTOM + (labeled ? 4 : 2)}
                        stroke="var(--text-muted)"
                        opacity={labeled ? 1 : 0.5}
                      />
                      {labeled && (
                        <text
                          x={tx}
                          y={VOL_BOTTOM + 14}
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

          {/* Left y-axis: premium ($). */}
          {yPrem &&
            leftTicks.map((v) => {
              const y = yPrem(v);
              if (y < PAD.top - 0.5 || y > PREM_BOTTOM + 0.5) return null;
              return (
                <g key={`L${v}`}>
                  <line
                    x1={PAD.left - 4}
                    x2={WIDTH - PAD.right}
                    y1={y}
                    y2={y}
                    stroke={COLORS.grid}
                  />
                  <text
                    x={PAD.left - 6}
                    y={y + 3}
                    textAnchor="end"
                    fontSize={9}
                    fontFamily="var(--font-mono)"
                    fill="var(--text-secondary)"
                  >
                    {fmtM(v)}
                  </text>
                </g>
              );
            })}

          {/* Right y-axis: spot price. */}
          {ySpot &&
            rightTicks.map((v) => {
              const y = ySpot(v);
              if (y < PAD.top - 0.5 || y > PREM_BOTTOM + 0.5) return null;
              return (
                <text
                  key={`R${v}`}
                  x={WIDTH - PAD.right + 6}
                  y={y + 3}
                  textAnchor="start"
                  fontSize={9}
                  fontFamily="var(--font-mono)"
                  fill={COLORS.spot}
                >
                  {v.toFixed(0)}
                </text>
              );
            })}

          {/* Volume filled area (per session). */}
          {sessionRanges.map((s) => {
            const d = volAreaForSession(s);
            return d ? (
              <path
                key={`vol-${s.date}`}
                d={d}
                fill={COLORS.vol}
                fillOpacity={0.14}
                stroke={COLORS.vol}
                strokeWidth={0.8}
                strokeOpacity={0.5}
              />
            ) : null;
          })}

          {/* Premium + spot series (premium on top of spot). */}
          <path
            d={spotPath}
            fill="none"
            stroke={COLORS.spot}
            strokeWidth={1.4}
            strokeLinecap="round"
          />
          <path
            d={callPath}
            fill="none"
            stroke={COLORS.call}
            strokeWidth={1.5}
            strokeLinecap="round"
          />
          <path
            d={putPath}
            fill="none"
            stroke={COLORS.put}
            strokeWidth={1.5}
            strokeLinecap="round"
          />
        </svg>
      </div>
    </div>
  );
}
