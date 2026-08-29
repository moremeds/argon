import { WIDE_FRAME } from "@/components/macro/chartGeometry";
import { BoardPanel } from "@/components/macro/domain/BoardPanel";
import type { components } from "@/lib/types";

import { CorrelationLineChart } from "./CorrelationLineChart";

// The viewBox is the type scale, not a drawing detail: everything inside scales by
// containerWidth / viewBoxWidth, TEXT INCLUDED. This chart kept its pre-desk 640-unit
// default while sitting in the ~1200px full-width panel, so it rendered at k=1.83 and
// magnified its own 11px labels to ~20px. Height preserves the chart's own 8:3 aspect
// rather than borrowing WIDE_FRAME's, so only the scale changes and not the shape.
const CHART_WIDTH = WIDE_FRAME.width;
const CHART_HEIGHT = Math.round((WIDE_FRAME.width * 240) / 640);

type History = components["schemas"]["GoldCorrelationHistory"];
type GaugePoint = components["schemas"]["GoldGaugeTimeSeriesPoint"];
type CorrelationPoint = components["schemas"]["GoldCorrelationPoint"];

/**
 * The gauge's own history, reshaped to the chart's point type.
 *
 * `GoldGaugeTimeSeriesPoint` is `{obs_date, corr_252d}` and `corr_252d` is nullable —
 * the early span of the series carries dates with no correlation yet, because a
 * 252-day window needs 252 days of history before it can produce a first value. Those
 * are dropped rather than plotted at zero: a null correlation is "not computable here",
 * and zero is "gold and the anchor moved independently", which is a different claim.
 */
function anchorSeries(points: GaugePoint[]): CorrelationPoint[] {
  return points
    .filter((p): p is GaugePoint & { corr_252d: string } => p.corr_252d != null)
    .map((p) => ({ obs_date: p.obs_date, value: p.corr_252d }));
}

/**
 * Board t5 — "Anchor decay · gauge corr_60d, daily".
 *
 * ### Why the heading does not say what the board's heading says
 *
 * The board asks for the 60-day correlation at daily resolution — the cut that shows an
 * anchor decaying rather than an average holding. **That series does not exist.** The
 * producer computes correlation at `window=252` only (`reports/gold_posture.py`), and
 * `GoldGaugeTimeSeriesPoint` carries a single `corr_252d` field, so there is no 60-day
 * value on any point of any series the API serves. Printing the board's heading over a
 * 252-day line would be the one failure mode this desk's own rules name repeatedly: a
 * label asserting a relationship the data underneath does not carry.
 *
 * So the heading names the window that is DRAWN, and the note below states the gap.
 *
 * ### What binding `/api/gold/gauge` actually bought
 *
 * Depth, not resolution. `state.correlation_history` carries 3-5 observations per pair
 * — enough for a direction, not enough for a decay. The gauge's `history_252d` is the
 * same 252-day window at ~261 observations spanning five years, and it was consumed by
 * nothing until 2026-08-29 (the board's §⑩ P2.2 lists it as one of three such routes).
 * It is drawn as the primary line; the three sparse pairs stay beside it because they
 * decompose the anchor into the channels the lenses actually read.
 *
 * Both counts are derived at render time. They move every night, and a figure hardcoded
 * from one capture is exactly the trap the desk's board-value rule exists to catch.
 */
export function CorrelationHistoryPanel({
  history,
  anchorHistory,
}: {
  history: History;
  /** `/api/gold/gauge` `history_252d`. Absent when that request failed — the panel then
   *  draws the sparse pairs alone and says so, rather than rendering an empty chart. */
  anchorHistory?: GaugePoint[] | null;
}) {
  const anchor = anchorHistory ? anchorSeries(anchorHistory) : [];
  const pairs = [
    {
      id: "gold_dfii10",
      label: "GOLD ↔ DFII10",
      color: "var(--positive, #05ad98)",
      points: history.gold_dfii10 ?? [],
    },
    {
      id: "gold_dxy",
      label: "GOLD ↔ DXY",
      color: "var(--warning, #f5a623)",
      points: history.gold_dxy ?? [],
    },
    {
      id: "gold_gpr",
      label: "GOLD ↔ GPR",
      // Fallback corrected 2026-08-29: `--info` is #8b5cf6 (violet), and this read
      // #3a8fd6 (blue). Invisible while the token resolves, wrong the moment it does not
      // — and #3a8fd6 is the sky blue that fails the normal-vision floor against
      // `--positive`, so the stale fallback named a colour the palette rejects.
      color: "var(--info, #8b5cf6)",
      points: history.gold_gpr ?? [],
    },
  ];
  const pairCount = pairs.reduce((n, s) => n + s.points.length, 0);

  return (
    <BoardPanel
      id="anchor-decay"
      title="Anchor decay · 252d rolling"
      questions={["Q4"]}
      basis="REAL"
      source={
        <>
          /api/gold/gauge history_252d ({anchor.length} obs) + /api/gold/state
          correlation_history ({pairCount} obs across three pairs)
        </>
      }
    >
      <div className="lgd">
        {anchor.length > 0 ? (
          <span>
            <i style={{ background: "var(--text-primary)" }} />
            anchor · gauge 252d
          </span>
        ) : null}
        {pairs.map((p) => (
          <span key={p.id}>
            <i style={{ background: p.color }} />
            {p.label}
          </span>
        ))}
      </div>
      <div className="chart">
        <CorrelationLineChart
          series={[
            ...(anchor.length > 0
              ? [
                  {
                    id: "gauge_anchor",
                    label: "ANCHOR (GAUGE)",
                    // Near-neutral ink, at weight, rather than a fourth hue.
                    //
                    // Measured with the palette validator against this surface (#060810):
                    // the obvious candidates fail. `--accent-vivid` #d946a8 separates from
                    // `--positive` by ΔE 4.6 under deuteranopia — below the floor, and the
                    // anchor-vs-DFII10 comparison is the one this panel exists to support.
                    // `--accent-cool` #38bdf8 fails even normal vision (ΔE 14.3 < 15).
                    //
                    // `--text-primary` passes CVD at 14.0 and normal vision at 25.3, and
                    // trips only the chroma floor — the validator correctly saying it reads
                    // gray. That is the intent: the anchor is not a fourth peer channel, it
                    // is the series the other three decompose, so it takes the ink the desk
                    // uses for primary values and `strokeWidth` carries the emphasis.
                    color: "var(--text-primary, #e2e8f0)",
                    strokeWidth: 2.25,
                    points: anchor,
                  },
                ]
              : []),
            ...pairs,
          ]}
          pre2022Band={history.pre_2022_band}
          width={CHART_WIDTH}
          height={CHART_HEIGHT}
        />
      </div>
      <p data-testid="correlation-history-window-note" className="cap">
        The board asks this chart for the gauge&rsquo;s 60-day correlation,
        daily — the cut that shows an anchor decaying rather than an average
        holding. The producer computes the history at a 252-day window only (
        <code>gold_posture.py</code>, <code>window=252</code>), so the shorter
        series does not exist to plot. The heading says which window this is
        rather than the one that was asked for, and the 60-day level sits in the
        transmission gauge above.{" "}
        {anchor.length > 0 ? (
          <>
            The anchor line carries <b>{anchor.length}</b> observations from the
            gauge against <b>{pairCount}</b> across the three decomposed pairs,
            which is why it is drawn as the primary series.
          </>
        ) : (
          <>
            The gauge history could not be read for this observation, so only
            the three decomposed pairs are drawn — <b>{pairCount}</b>{" "}
            observations in total. This is a missing request, not a missing
            series.
          </>
        )}
      </p>
    </BoardPanel>
  );
}
