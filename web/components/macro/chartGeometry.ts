/**
 * Shared frames for the hand-rolled SVG charts across the macro desk's tabs.
 *
 * `.chart svg` is `width: 100%; height: auto`, so a fixed viewBox is not a drawing
 * detail -- it is the type scale. Everything inside scales by
 * `containerWidth / viewBoxWidth`, TEXT INCLUDED, so a chart drawn at 780 units inside
 * a 1200px panel silently magnified its own labels ~1.5x. The `.svgLabel` rule says
 * 11px and roughly 17px arrived.
 *
 * The thing to hold equal is therefore the SCALE FACTOR, not the viewBox. The charts
 * that use these frames now draw their `viewBox` width from the container's MEASURED
 * pixel width (`useChartWidth`), so the factor is exactly 1 at every viewport and the
 * designed font sizes render at face value. The frame `width` remains as the
 * SSR/jsdom fallback -- vitest and the server render keep this geometry -- while the
 * heights and pads below are still the shared fixed geometry.
 *
 * The heights are the other half of the old bug. At aspect 1.95 a full-width chart
 * wanted to be over 600px tall, and `.chartPanel svg { min-height: 420px }` then
 * letterboxed a shape that no longer needed it -- the empty band above the plot was
 * `preserveAspectRatio` centring the drawing, not padding.
 */

export type ChartFrame = {
  width: number;
  height: number;
  padLeft: number;
  padRight: number;
  padTop: number;
  padBottom: number;
  plotW: number;
  plotH: number;
  /** Baselines for the alternating x-axis label rows, measured from the bottom. */
  xLabelNear: number;
  xLabelFar: number;
};

function frame(
  width: number,
  height: number,
  pad: { left: number; right: number; top: number; bottom: number },
): ChartFrame {
  return {
    width,
    height,
    padLeft: pad.left,
    padRight: pad.right,
    padTop: pad.top,
    padBottom: pad.bottom,
    plotW: width - pad.left - pad.right,
    plotH: height - pad.top - pad.bottom,
    xLabelNear: height - 30,
    xLabelFar: height - 14,
  };
}

/**
 * Full-width chart panels: the SEP dot plot and the dealer path. Width is the
 * fallback for SSR/jsdom; the client draws at the container's measured width.
 */
export const WIDE_FRAME = frame(1200, 360, {
  left: 64,
  right: 28,
  top: 28,
  bottom: 56,
});

/**
 * The narrower grid cell the yield curve shares with its slope table. Width is
 * the fallback for SSR/jsdom; the client draws at the cell's measured width.
 */
export const NARROW_FRAME = frame(760, 300, {
  left: 58,
  right: 24,
  top: 24,
  bottom: 44,
});

/**
 * The gold structural panel is one cell of a three-column board row. Its chart flexes
 * beside (or above) a 220px country picker and measures about 391px on the 1440px macro
 * canvas. A bare width rather than a `ChartFrame` is intentional because the component
 * owns its padding; 400 keeps its SVG scale near 1 across that measured container.
 */
export const GOLD_STRUCTURAL_WIDTH = 400;

export const AXIS_TICK_COUNT = 5;

/** Evenly spaced y-axis tick values across a [lo, lo + span] domain. */
export function axisTicks(
  lo: number,
  span: number,
  count = AXIS_TICK_COUNT,
): number[] {
  return Array.from(
    { length: count },
    (_, index) => lo + (span * index) / (count - 1),
  );
}
