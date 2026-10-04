import type { ReactNode } from "react";
import type { SvgFrame } from "@/lib/svgChart";

/** The four corner labels a chartFrame() chart carries: the y range on the
 *  left edge, the first and last x values along the bottom (I-106). */
export function FrameLabels({
  frame: { W, H, M },
  yLo,
  yHi,
  xFirst,
  xLast,
}: {
  frame: SvgFrame;
  yLo: ReactNode;
  yHi: ReactNode;
  xFirst: ReactNode;
  xLast: ReactNode;
}) {
  return (
    <>
      <text
        x={M.left - 4}
        y={H - M.bottom}
        fontSize={9}
        textAnchor="end"
        fill="var(--text-muted)"
      >
        {yLo}
      </text>
      <text
        x={M.left - 4}
        y={M.top + 8}
        fontSize={9}
        textAnchor="end"
        fill="var(--text-muted)"
      >
        {yHi}
      </text>
      <text x={M.left} y={H - 4} fontSize={9} fill="var(--text-muted)">
        {xFirst}
      </text>
      <text
        x={W - M.right}
        y={H - 4}
        fontSize={9}
        textAnchor="end"
        fill="var(--text-muted)"
      >
        {xLast}
      </text>
    </>
  );
}
