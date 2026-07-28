"use client";

/**
 * VcgZScoreHistoryChart — the VCG z-score series as bars + a smooth curve.
 *
 * IMPORTANT, and a deliberate departure from the reference mock this was
 * modelled on: the mock's subtitle read `z = (VCG - 20-session mean) / sigma`,
 * i.e. it re-standardised VCG on the client over a 20-session window. That is
 * wrong twice over for this codebase.
 *
 * `vcg` as served by /api/regime/vcg/history is ALREADY a z-score —
 * `cards/vcg_scoring.standardise_residuals` takes a trailing z of the
 * VIX/VVIX→credit OLS residual over `Z_WINDOW = 63` sessions. Re-z-scoring it
 * would be double standardisation (a z-of-a-z), which rescales the axis so the
 * ±2 / ±2.5 trigger thresholds the scanner actually fires on no longer land at
 * ±2 / ±2.5 on the chart. The window is also 63, not 20.
 *
 * So this plots `vcg` directly and labels the real definition.
 */

import { useMemo, useState } from "react";
import type { VcgDailyEntry } from "@/lib/regime/useVcgSeries";
import { linearScale, pathFromPointsSmooth, type Point } from "@/lib/svgChart";
import InfoTooltip from "../InfoTooltip";

/** Trading sessions per range. The widest keeps whatever the fetch returned.
 *
 *  It is labelled 1Y, not ALL: `/api/regime/vcg/history` caps `days` at 365,
 *  so the widest window this can ever show is a year — while the table holds
 *  ~4.7k sessions back to 2007. "ALL" would promise the whole history and
 *  quietly deliver the last year of it. Widening it is a backend change
 *  (the `le=365` Query bound), not a frontend one. */
const RANGES: { key: string; sessions: number | null }[] = [
  { key: "1M", sessions: 21 },
  { key: "3M", sessions: 63 },
  { key: "6M", sessions: 126 },
  { key: "1Y", sessions: null },
];

const W = 1000;
const H = 300;
const PAD = { top: 16, right: 24, bottom: 34, left: 52 };
const PLOT_W = W - PAD.left - PAD.right;
const PLOT_H = H - PAD.top - PAD.bottom;

/** The scanner's own trigger levels — the reason the axis is pinned to ±3. */
const Y_TICKS = [3, 2, 1, 0, -1, -2, -3];

/** The scanner's own trigger levels, drawn as rules (mirrored to ±). */
const ARM_LEVELS = [
  { z: 2.0, color: "var(--warning)" },
  { z: 2.5, color: "var(--fault)" },
];

/** The calm core — the half of this chart that carries validated information.
 *
 *  ARM_LEVELS above are what the scanner *fires* on, and they are the weaker
 *  end of the evidence: the tails carry no directional signal (max |t| vs the
 *  rest of the sample = 1.10 across 30 cells) and their forward-vol lift is
 *  crisis-driven — dramatic means, but a median lift of only +2.1pt.
 *
 *  |z| < 0.75 is the opposite case. Fourteen independent expanding training
 *  windows each selected exactly this threshold, it beat a trailing-252 VIX
 *  filter 4/4 on the VRP macro book, and it is near-orthogonal to VIX by
 *  construction (rho = -0.030 — `vcg` is already an OLS residual). Without
 *  this band the chart is visually loudest precisely where the evidence is
 *  thinnest and silent where it is strongest.
 *
 *  Drawn as a band rather than a rule because it is a standing condition, not
 *  an event, and behind the bars so it never competes with the data.
 *  Deliberately NOT labelled as a trading threshold: it validated on 20-day
 *  holds and reverses on 0.25delta/30d, so the honest claim is "below-baseline
 *  forward vol", not "enter here".
 *  See docs/research/2026-07-29-vcg-vs-vix-walkforward.md. */
const CALM_BAND = 0.75;

export type VcgZPoint = { date: string; z: number };

/**
 * Keep only rows with a finite `vcg`, oldest→newest, then take the last
 * `sessions`. Exported for unit testing.
 *
 * Null `vcg` rows are dropped rather than gap-rendered: VCG is undefined for
 * the first Z_WINDOW sessions of any series, so the nulls cluster at the head
 * where they carry no information.
 */
export function selectZSeries(
  rows: VcgDailyEntry[] | null | undefined,
  sessions: number | null,
): VcgZPoint[] {
  const clean: VcgZPoint[] = [];
  for (const r of rows ?? []) {
    if (typeof r.vcg !== "number" || !Number.isFinite(r.vcg)) continue;
    if (!r.date) continue;
    clean.push({ date: String(r.date), z: r.vcg });
  }
  clean.sort((a, b) => a.date.localeCompare(b.date));
  return sessions == null ? clean : clean.slice(-sessions);
}

function fmtDate(iso: string): string {
  // Parse as UTC parts, not `new Date(iso)` — the latter reads a bare
  // YYYY-MM-DD as UTC midnight and then renders it in local time, which shows
  // the previous day for anyone west of Greenwich.
  const [y, m, d] = iso.split("-").map(Number);
  if (!y || !m || !d) return iso;
  const month = new Date(Date.UTC(y, m - 1, d)).toLocaleString("en-US", {
    month: "short",
    timeZone: "UTC",
  });
  return `${month} ${d}`;
}

function zColor(z: number): string {
  return z >= 0 ? "var(--signal-core)" : "var(--fault)";
}

export default function VcgZScoreHistoryChart({
  rows,
  interpretation,
}: {
  rows: VcgDailyEntry[] | null | undefined;
  interpretation?: string | null;
}) {
  const [range, setRange] = useState("1M");

  const series = useMemo(
    () =>
      selectZSeries(
        rows,
        RANGES.find((r) => r.key === range)?.sessions ?? null,
      ),
    [rows, range],
  );

  // How much history exists at all — drives which range buttons are offered.
  const total = useMemo(() => selectZSeries(rows, null).length, [rows]);

  const latest = series.length ? series[series.length - 1] : null;
  const prior = series.length > 1 ? series[series.length - 2] : null;
  const delta = latest && prior ? latest.z - prior.z : null;

  if (series.length < 2) {
    return (
      <div className="section" data-testid="vcg-zscore-history">
        <div className="section-header">
          <div className="section-title">VCG Z-Score History</div>
        </div>
        <div
          style={{
            padding: 24,
            fontFamily: "var(--font-mono)",
            fontSize: 11,
            color: "var(--text-muted)",
          }}
        >
          Not enough scored sessions yet — VCG is undefined until 63 sessions of
          history exist.
        </div>
      </div>
    );
  }

  // Symmetric axis pinned to at least ±3 so the ±2 / ±2.5 trigger lines sit in
  // a fixed place across ranges; grows only if the data actually exceeds it.
  const bound = Math.max(3, ...series.map((p) => Math.abs(p.z)));
  const y = linearScale([-bound, bound], [PAD.top + PLOT_H, PAD.top]);
  const band = PLOT_W / series.length;
  const cx = (i: number) => PAD.left + band * (i + 0.5);
  const barW = Math.max(1, band * 0.7);
  const zeroY = y(0);
  const points: Point[] = series.map((p, i) => [cx(i), y(p.z)]);

  // Label roughly every ~6 bands, always including the last.
  const step = Math.max(1, Math.ceil(series.length / 6));
  const ticks = series
    .map((p, i) => ({ p, i }))
    .filter(({ i }) => i % step === 0 || i === series.length - 1);

  return (
    <div className="section" data-testid="vcg-zscore-history">
      <div className="section-header">
        <div className="section-title">
          VCG Z-Score History
          {/* Both ends get named, because the chart now draws both and they
              carry very different evidential weight. Saying only what the
              scanner fires on would leave the shaded band unexplained — and
              would keep implying the tails are the informative part. */}
          <InfoTooltip text="Trailing 63-session z-score of the VIX/VVIX→credit OLS residual (Z_WINDOW=63). This is the same value the scanner triggers on: |z| ≥ 2.0 arms the signal, ≥ 2.5 escalates to RISK_OFF — those mark coincident vol/credit stress and do NOT predict SPX direction. The shaded ±0.75 calm core is the better-evidenced half: it marks below-baseline forward realised volatility, was independently selected by 14 walk-forward training windows, and is near-orthogonal to VIX (ρ = −0.03). It is a short-vol permission condition on ~20-day holds, not an entry trigger." />
        </div>
        {latest && (
          <div style={{ textAlign: "right" }}>
            <div
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 22,
                fontWeight: 700,
                color: zColor(latest.z),
              }}
              data-testid="vcg-zscore-history-latest"
            >
              {latest.z >= 0 ? "+" : ""}
              {latest.z.toFixed(2)}
            </div>
            <div
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 10,
                color: "var(--text-muted)",
                letterSpacing: "0.08em",
              }}
            >
              {interpretation ?? "—"}
              {delta != null && (
                <>
                  {" · "}
                  {delta >= 0 ? "+" : ""}
                  {delta.toFixed(2)}σ vs prior
                </>
              )}
            </div>
          </div>
        )}
      </div>

      <div className="section-body">
        <div
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 10,
            color: "var(--text-muted)",
            letterSpacing: "0.08em",
          }}
        >
          z = trailing 63-session z-score of the model residual
        </div>

        <div style={{ display: "flex", gap: 6, margin: "10px 0 4px" }}>
          {RANGES.map((r) => {
            // Offering a range the data can't fill renders a chart identical to
            // the one before it, which reads as a broken button.
            const available = r.sessions == null || total > (r.sessions ?? 0);
            if (!available && r.key !== "1Y" && r.key !== "1M") return null;
            return (
              <button
                key={r.key}
                type="button"
                onClick={() => setRange(r.key)}
                data-testid={`vcg-z-range-${r.key}`}
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: 11,
                  letterSpacing: "0.08em",
                  padding: "4px 12px",
                  cursor: "pointer",
                  borderRadius: 4,
                  border: "1px solid var(--border-dim)",
                  background:
                    range === r.key ? "var(--signal-core)" : "transparent",
                  color:
                    range === r.key ? "var(--bg-panel)" : "var(--text-muted)",
                }}
              >
                {r.key}
              </button>
            );
          })}
        </div>

        <svg
          viewBox={`0 0 ${W} ${H}`}
          width="100%"
          role="img"
          style={{ fontFamily: "var(--font-mono)", fontSize: 11 }}
        >
          <title>{`VCG z-score, last ${series.length} sessions`}</title>

          {/* Calm core, first so everything else paints over it. */}
          <rect
            x={PAD.left}
            y={y(CALM_BAND)}
            width={PLOT_W}
            height={y(-CALM_BAND) - y(CALM_BAND)}
            fill="var(--positive)"
            opacity={0.07}
          />

          {Y_TICKS.filter((t) => Math.abs(t) <= bound).map((t) => (
            <g key={t}>
              <line
                x1={PAD.left}
                y1={y(t)}
                x2={PAD.left + PLOT_W}
                y2={y(t)}
                stroke="var(--border-dim)"
                strokeDasharray={t === 0 ? "4 4" : undefined}
                opacity={t === 0 ? 1 : 0.45}
              />
              <text
                x={PAD.left - 8}
                y={y(t) + 4}
                textAnchor="end"
                fill="var(--text-muted)"
                fontSize={10}
              >
                {t > 0 ? `+${t.toFixed(2)}` : t.toFixed(2)}
              </text>
            </g>
          ))}

          {/* The two levels the scanner actually fires on. Without these the
              tooltip tells you |z| ≥ 2.0 arms and ≥ 2.5 escalates, and the
              chart gives you no way to see whether today is near either — the
              integer gridlines above are axis furniture, and 2.5 isn't among
              them at all. Warning below RISK_OFF, matching the badge colours. */}
          {ARM_LEVELS.filter(({ z }) => z <= bound).flatMap(({ z, color }) =>
            [z, -z].map((v) => (
              <line
                key={`arm-${v}`}
                x1={PAD.left}
                y1={y(v)}
                x2={PAD.left + PLOT_W}
                y2={y(v)}
                stroke={color}
                strokeDasharray="2 5"
                opacity={0.55}
              />
            )),
          )}

          {/* Bars: the actual per-session values. The curve is a reading aid. */}
          {series.map((p, i) => (
            <rect
              key={p.date}
              x={cx(i) - barW / 2}
              y={Math.min(zeroY, y(p.z))}
              width={barW}
              height={Math.abs(y(p.z) - zeroY)}
              fill={zColor(p.z)}
              opacity={0.22}
            />
          ))}

          <path
            d={pathFromPointsSmooth(points)}
            fill="none"
            stroke="var(--signal-core)"
            strokeWidth={2}
            strokeLinejoin="round"
            strokeLinecap="round"
          />

          <circle
            cx={points[points.length - 1][0]}
            cy={points[points.length - 1][1]}
            r={4.5}
            // Sign-coloured, not fixed teal: it marks the latest value, and a
            // teal dot beside a red "-0.43" readout contradicts itself.
            fill={zColor(series[series.length - 1].z)}
            stroke="var(--bg-panel)"
            strokeWidth={2}
          />

          {ticks.map(({ p, i }) => (
            <text
              key={p.date}
              x={cx(i)}
              y={PAD.top + PLOT_H + 20}
              textAnchor="middle"
              fill="var(--text-muted)"
              fontSize={10}
            >
              {fmtDate(p.date)}
            </text>
          ))}
        </svg>
      </div>
    </div>
  );
}
