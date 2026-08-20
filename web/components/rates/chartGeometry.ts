/**
 * Shared frames for the hand-rolled SVG charts on the rates desk.
 *
 * These are sized by `viewBox` and stretched to `width: 100%`, so the viewBox is not a
 * drawing detail -- it is the type scale. Everything inside scales by
 * `containerWidth / viewBoxWidth`, TEXT INCLUDED, so a chart drawn at 780 units inside
 * a 1200px panel silently magnified its own labels ~1.5x. The `.svgLabel` rule says
 * 11px and roughly 17px arrived.
 *
 * The thing to hold equal is therefore the SCALE FACTOR, not the viewBox. Two charts
 * sharing one viewBox in containers of different widths render at different text
 * sizes -- which is the state this replaced, where the two policy paths sat full width
 * at 780x400 and the curve sat in a ~760px grid cell at 760x320, magnifying by 1.54x
 * and 0.99x respectively. So each frame below is sized to the container it is actually
 * rendered into, giving every chart a scale near 1 and one shared type size.
 *
 * Measured in a 1512px viewport: the full-width chart panel is ~1200px, the curve grid
 * cell ~760px (`.curveGrid` gives it 1.4fr of the 1440px shell).
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

/** Full-width chart panels: the SEP dot plot and the dealer path. */
export const WIDE_FRAME = frame(1200, 360, {
  left: 64,
  right: 28,
  top: 28,
  bottom: 56,
});

/** The narrower grid cell the yield curve shares with its slope table. */
export const NARROW_FRAME = frame(760, 300, {
  left: 58,
  right: 24,
  top: 24,
  bottom: 44,
});

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
