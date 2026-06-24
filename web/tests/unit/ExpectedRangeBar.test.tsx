/* @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ExpectedRangeBar } from "@/components/regime/gex/ExpectedRangeBar";
import type { GexData } from "@/lib/regime/useGex";

// Real SPX snapshot (2026-06-16): spot ± iv_1d band + dealer levels, frozen.
const lvl = (strike: number) => ({ strike }) as GexData["levels"]["gex_flip"];
const data = {
  data_date: "2026-06-16",
  spot: 7554.29,
  prev_close: 7431.46,
  expected_range: { low: 7490.52, high: 7618.06, iv_1d: 0.8441 },
  levels: {
    gex_flip: lvl(7425),
    max_magnet: lvl(7600),
    second_magnet: lvl(7550),
    max_accelerator: lvl(7200),
    put_wall: lvl(7500),
    call_wall: lvl(7600),
  },
} as unknown as GexData;

describe("ExpectedRangeBar", () => {
  it("anchors each value+name label at its marker's pct (alignment bug)", () => {
    const { container } = render(<ExpectedRangeBar data={data} />);
    // the flip label and the flip marker must share the exact same `left`
    const flipMarker = container.querySelector<HTMLElement>(
      '[title^="GEX FLIP"]',
    );
    const flipLabel = screen.getByTestId("exp-range-label-flip");
    expect(flipMarker).not.toBeNull();
    expect(flipMarker!.style.left).not.toBe("");
    expect(flipLabel.style.left).toBe(flipMarker!.style.left);

    // and spot likewise — a regression to flex labels would break this
    const spotMarker = container.querySelector<HTMLElement>('[title^="SPOT"]');
    const spotLabel = screen.getByTestId("exp-range-label-spot");
    expect(spotLabel.style.left).toBe(spotMarker!.style.left);
  });

  it("renders a label per existing level + the expected-move summary", () => {
    render(<ExpectedRangeBar data={data} />);
    for (const k of ["accel", "flip", "close", "spot", "magnet"]) {
      expect(screen.getByTestId(`exp-range-label-${k}`)).toBeTruthy();
    }
    // move = (high − low)/2 = 63.77; iv_1d = 0.84%
    expect(screen.getByText(/Expected ±63\.77/)).toBeTruthy();
    expect(screen.getByText(/±0\.84%/)).toBeTruthy();
  });

  it("returns null when the expected range is unavailable", () => {
    const { container } = render(
      <ExpectedRangeBar
        data={
          {
            ...data,
            expected_range: { low: null, high: null, iv_1d: null },
          } as GexData
        }
      />,
    );
    expect(container.firstChild).toBeNull();
  });
});
