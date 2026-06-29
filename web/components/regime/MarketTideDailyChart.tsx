"use client";

import {
  finiteDomain,
  linearScale,
  niceTicks,
  pathFromNullablePoints,
} from "@/lib/svgChart";
import type {
  MarketTidePoint,
  MarketTideSession,
} from "@/lib/regime/useMarketTide";

const WIDTH = 880;
const HEIGHT = 380;
const PAD = { top: 14, right: 66, bottom: 30, left: 54 };
// Net Premiums + SPY share the top band; Net Volume gets the bottom band.
const PREM_TOP = PAD.top + 14;
const PREM_BOTTOM = 248;
const VOL_LABEL_Y = 266;
const VOL_TOP = 280;
const VOL_BOTTOM = HEIGHT - PAD.bottom;

const COLORS = {
  spy: "var(--accent-warm, #F5A623)",
  call: "var(--positive, #22c55e)",
  put: "var(--negative, #ef4444)",
  grid: "rgba(148,163,184,0.08)",
  zero: "var(--border-dim)",
  muted: "var(--text-muted)",
};

const ET_TZ = "America/New_York";
const _etFmt = new Intl.DateTimeFormat("en-US", {
  timeZone: ET_TZ,
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

function etMinutes(ts: string): number {
  const parts = _etFmt.formatToParts(new Date(ts));
  const h = Number(parts.find((p) => p.type === "hour")?.value ?? 0);
  const min = Number(parts.find((p) => p.type === "minute")?.value ?? 0);
  return h * 60 + min;
}

function hhmm(min: number): string {
  const h = Math.floor(min / 60);
  const m = min % 60;
  return `${h}:${String(m).padStart(2, "0")}`;
}

/** "YYYY-MM-DD" → "D/M" (e.g. 26/6) in ET. */
function dmLabel(d: string): string {
  const [, m, day] = d.split("-");
  return `${Number(day)}/${Number(m)}`;
}

/** "YYYY-MM-DD" → "26 Jun" in ET. */
function dMonLabel(d: string): string {
  const dt = new Date(`${d}T12:00:00-04:00`);
  return dt.toLocaleDateString("en-US", {
    day: "numeric",
    month: "short",
    timeZone: ET_TZ,
  });
}

function fmtM(v: number | null): string {
  if (v == null) return "—";
  const m = v / 1_000_000;
  if (Math.abs(m) >= 1000) return `${(m / 1000).toFixed(1)}B`;
  return `${m.toFixed(0)}M`;
}

function fmtVol(v: number | null): string {
  if (v == null) return "—";
  const a = Math.abs(v);
  if (a >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (a >= 1000) return `${(v / 1000).toFixed(0)}K`;
  return `${v}`;
}

// RTH window in ET minutes — 09:30 → 16:00.
const RTH_OPEN = 9 * 60 + 30;
const RTH_CLOSE = 16 * 60;

function Stat({ color, label }: { color: string; label: string }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
      <span
        style={{
          width: 7,
          height: 7,
          borderRadius: "50%",
          background: color,
          display: "inline-block",
        }}
      />
      <span style={{ color: "var(--text-secondary)" }}>{label}</span>
    </span>
  );
}

export function MarketTideDailyChart({
  session,
  spotTicker,
}: {
  session: MarketTideSession | null;
  spotTicker: string;
}) {
  const points: MarketTidePoint[] = session?.points ?? [];
  const hasData = points.length >= 2;

  // Latest readings for the stats line (last bar; last non-null spot).
  const last = points.length ? points[points.length - 1] : null;
  const lastSpot =
    [...points].reverse().find((p) => p.spot != null)?.spot ?? null;
  const lastTime = last ? hhmm(etMinutes(last.ts)) : "—";

  const xScale = linearScale(
    [RTH_OPEN, RTH_CLOSE],
    [PAD.left, WIDTH - PAD.right],
  );
  const xOf = (p: MarketTidePoint) => xScale(etMinutes(p.ts));

  const premD = finiteDomain(
    points.flatMap((p) => [p.net_call_premium, p.net_put_premium]),
  );
  const spyD = finiteDomain(points.map((p) => p.spot));
  const volD = finiteDomain(points.map((p) => p.net_volume));

  const ySpy = spyD
    ? linearScale([spyD.lo, spyD.hi], [PREM_BOTTOM, PREM_TOP])
    : null;
  const yPrem = premD
    ? linearScale([premD.lo, premD.hi], [PREM_BOTTOM, PREM_TOP])
    : null;
  // Volume baseline at 0 (bottom of band), filling upward — UW layout.
  const volLo = volD ? Math.min(0, volD.lo) : 0;
  const volHi = volD ? Math.max(1, volD.hi) : 1;
  const yVol = linearScale([volLo, volHi], [VOL_BOTTOM, VOL_TOP]);

  function pathFor(
    accessor: (p: MarketTidePoint) => number | null,
    scale: ((v: number) => number) | null,
  ): string {
    if (scale == null) return "";
    return pathFromNullablePoints(
      points.map((p): [number, number] | null => {
        const v = accessor(p);
        return v == null || !Number.isFinite(v) ? null : [xOf(p), scale(v)];
      }),
    );
  }

  /** Net-volume area from the 0 baseline (green up / red down). */
  function volArea(sign: 1 | -1): string {
    const y0 = yVol(0);
    const pts: [number, number][] = [];
    for (const p of points) {
      const v = p.net_volume;
      if (v == null || !Number.isFinite(v)) continue;
      const clamped = sign > 0 ? Math.max(0, v) : Math.min(0, v);
      pts.push([xOf(p), yVol(clamped)]);
    }
    if (pts.length < 2) return "";
    const body = pts.map(([x, y]) => `L${x},${y}`).join(" ");
    return `M${pts[0][0]},${y0} ${body} L${pts[pts.length - 1][0]},${y0} Z`;
  }

  const spyPath = pathFor((p) => p.spot, ySpy);
  const callPath = pathFor((p) => p.net_call_premium, yPrem);
  const putPath = pathFor((p) => p.net_put_premium, yPrem);

  const spyTicks = spyD ? niceTicks(spyD.lo, spyD.hi, 4) : [];
  const premTicks = premD ? niceTicks(premD.lo, premD.hi, 5) : [];
  const volTicks = niceTicks(volLo, volHi, 3);
  // Six evenly-spaced clock ticks across RTH; the first carries the date.
  const xTicks = Array.from({ length: 6 }, (_, i) =>
    Math.round(RTH_OPEN + (i * (RTH_CLOSE - RTH_OPEN)) / 5),
  );

  return (
    <div
      className="section"
      data-testid="market-tide-daily"
      style={{ height: "100%", display: "flex", flexDirection: "column" }}
    >
      <div
        className="section-body"
        style={{
          padding: "12px",
          flex: 1,
          minHeight: 0,
          display: "flex",
          flexDirection: "column",
        }}
      >
        {/* Stats line — date/time + latest SPY / Vol / Net Put / Net Call. */}
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            alignItems: "center",
            gap: 14,
            fontFamily: "var(--font-mono)",
            fontSize: 13,
            marginBottom: 8,
          }}
        >
          <span style={{ color: "var(--text-primary)", fontWeight: 600 }}>
            {session ? dmLabel(session.date) : "—"}{" "}
            <span style={{ color: "var(--text-muted)", fontWeight: 400 }}>
              {lastTime}
            </span>
          </span>
          <Stat
            color={COLORS.spy}
            label={`${spotTicker}: ${lastSpot != null ? lastSpot.toFixed(1) : "—"}`}
          />
          <Stat
            color={COLORS.call}
            label={`Vol: ${fmtVol(last?.net_volume ?? null)}`}
          />
          <Stat
            color={COLORS.put}
            label={`NPP: ${fmtM(last?.net_put_premium ?? null)}`}
          />
          <Stat
            color={COLORS.call}
            label={`NCP: ${fmtM(last?.net_call_premium ?? null)}`}
          />
        </div>

        {!hasData ? (
          <div
            style={{
              padding: 24,
              textAlign: "center",
              color: "var(--text-muted)",
              fontFamily: "var(--font-mono)",
              fontSize: 12,
            }}
          >
            No intraday market-tide data for this session yet.
          </div>
        ) : (
          <svg
            role="img"
            aria-label={`Market tide — ${spotTicker} spot, net call/put premium, net volume`}
            viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
            preserveAspectRatio="none"
            style={{ width: "100%", flex: 1, minHeight: 0, display: "block" }}
          >
            <title>Market tide — spot, net call/put premium, net volume</title>

            {/* Band labels. */}
            <text
              x={PAD.left}
              y={PAD.top + 2}
              fontSize={12}
              fontFamily="var(--font-mono)"
              fill="var(--text-secondary)"
            >
              Net Premiums
            </text>
            <text
              x={PAD.left}
              y={VOL_LABEL_Y + 2}
              fontSize={12}
              fontFamily="var(--font-mono)"
              fill="var(--text-secondary)"
            >
              Net Volume
            </text>

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

            {/* Hourly-ish x-axis ticks across RTH; first carries the date. */}
            {xTicks.map((m, i) => {
              const tx = xScale(m);
              const label =
                i === 0 && session ? dMonLabel(session.date) : hhmm(m);
              return (
                <g key={`x${m}`}>
                  <line
                    x1={tx}
                    x2={tx}
                    y1={VOL_BOTTOM}
                    y2={VOL_BOTTOM + 4}
                    stroke="var(--text-muted)"
                    opacity={0.5}
                  />
                  <text
                    x={i === 0 ? PAD.left : tx}
                    y={VOL_BOTTOM + 16}
                    textAnchor={i === 0 ? "start" : "middle"}
                    fontSize={11}
                    fontFamily="var(--font-mono)"
                    fill="var(--text-muted)"
                  >
                    {label}
                  </text>
                </g>
              );
            })}

            {/* Left y-axis: SPY price (gold). */}
            {ySpy &&
              spyTicks.map((v) => {
                const y = ySpy(v);
                if (y < PREM_TOP - 0.5 || y > PREM_BOTTOM + 0.5) return null;
                return (
                  <g key={`spy${v}`}>
                    <line
                      x1={PAD.left}
                      x2={WIDTH - PAD.right}
                      y1={y}
                      y2={y}
                      stroke={COLORS.grid}
                    />
                    <text
                      x={PAD.left - 6}
                      y={y + 3}
                      textAnchor="end"
                      fontSize={12}
                      fontFamily="var(--font-mono)"
                      fill={COLORS.spy}
                    >
                      {v.toFixed(0)}
                    </text>
                  </g>
                );
              })}

            {/* Right y-axis: net premium ($). */}
            {yPrem &&
              premTicks.map((v) => {
                const y = yPrem(v);
                if (y < PREM_TOP - 0.5 || y > PREM_BOTTOM + 0.5) return null;
                return (
                  <text
                    key={`prem${v}`}
                    x={WIDTH - PAD.right + 6}
                    y={y + 3}
                    textAnchor="start"
                    fontSize={12}
                    fontFamily="var(--font-mono)"
                    fill="var(--text-secondary)"
                  >
                    {fmtM(v)}
                  </text>
                );
              })}

            {/* Right y-axis: net volume. */}
            {volTicks.map((v) => {
              const y = yVol(v);
              if (y < VOL_TOP - 0.5 || y > VOL_BOTTOM + 0.5) return null;
              return (
                <text
                  key={`vol${v}`}
                  x={WIDTH - PAD.right + 6}
                  y={y + 3}
                  textAnchor="start"
                  fontSize={11}
                  fontFamily="var(--font-mono)"
                  fill="var(--text-muted)"
                >
                  {fmtVol(v)}
                </text>
              );
            })}

            {/* Net-volume area (bright green up / red down from 0 baseline). */}
            <path d={volArea(1)} fill={COLORS.call} fillOpacity={0.5} />
            <path d={volArea(-1)} fill={COLORS.put} fillOpacity={0.5} />

            {/* SPY spot (drawn first so premium lines sit on top). */}
            <path
              d={spyPath}
              fill="none"
              stroke={COLORS.spy}
              strokeWidth={1.6}
              strokeLinecap="round"
            />
            <path
              d={callPath}
              fill="none"
              stroke={COLORS.call}
              strokeWidth={1.6}
              strokeLinecap="round"
            />
            <path
              d={putPath}
              fill="none"
              stroke={COLORS.put}
              strokeWidth={1.6}
              strokeLinecap="round"
            />
          </svg>
        )}
      </div>
    </div>
  );
}
