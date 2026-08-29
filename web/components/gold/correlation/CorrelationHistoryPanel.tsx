import { BoardPanel } from "@/components/macro/domain/BoardPanel";
import type { components } from "@/lib/types";

import { CorrelationLineChart } from "./CorrelationLineChart";

// This panel is one cell in the Gold tab's two-column grid. At the Regime-width desk it
// gives the SVG about 620px after panel/chart padding; the old 1200-unit full-width frame
// shrank labels to half size. Keep the chart's own 8:3 shape while matching this measured
// container, so only the coordinate scale changes and not the plot geometry.
const CHART_WIDTH = 620;
const CHART_HEIGHT = Math.round((CHART_WIDTH * 240) / 640);

type History = components["schemas"]["GoldCorrelationHistory"];
type GaugePoint = components["schemas"]["GoldGauge60dTimeSeriesPoint"];
type CorrelationPoint = components["schemas"]["GoldCorrelationPoint"];

/**
 * The gauge's own history, reshaped to the chart's point type.
 *
 * Null correlations are dropped rather than plotted at zero: a null correlation is
 * "not computable here",
 * and zero is "gold and the anchor moved independently", which is a different claim.
 */
function anchorSeries(points: GaugePoint[]): CorrelationPoint[] {
  return points
    .filter((p): p is GaugePoint & { corr_60d: string } => p.corr_60d != null)
    .map((p) => ({ obs_date: p.obs_date, value: p.corr_60d }));
}

/**
 * Board t5 — "Anchor decay · gauge corr_60d, daily".
 *
 * The primary line is the persisted daily 60-day gauge history. The three sparse pair
 * histories remain beside it because they decompose the anchor into the channels the
 * lenses read. Counts are derived at render time; no value comes from the board capture.
 */
export function CorrelationHistoryPanel({
  history,
  anchorHistory,
}: {
  history: History;
  /** `/api/gold/gauge` `history_60d`. Absent when that request failed — the panel then
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
      title="Anchor decay · gauge corr_60d, daily"
      questions={["Q4"]}
      basis="REAL"
      source={
        <>
          gold_posture_daily gauge corr_60d ({anchor.length} observations) + /api/gold/state
          correlation_history ({pairCount} obs across three pairs)
        </>
      }
    >
      <div className="lgd">
        {anchor.length > 0 ? (
          <span>
            <i style={{ background: "var(--text-primary)" }} />
            anchor · gauge 60d
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
        The anchor is the persisted 60-day rolling correlation at daily
        resolution — the cut that can show a relationship decaying instead of
        averaging two regimes together.{" "}
        {anchor.length > 0 ? (
          <>
            The anchor line carries <b>{anchor.length}</b> observations against <b>{pairCount}</b> across the three decomposed pairs,
            which is why it is drawn as the primary series.
          </>
        ) : (
          <>
            The persisted 60-day gauge history could not be read, so only
            the three decomposed pairs are drawn — <b>{pairCount}</b>{" "}
            observations in total. This is a missing request, not a missing
            series.
          </>
        )}
      </p>
    </BoardPanel>
  );
}
