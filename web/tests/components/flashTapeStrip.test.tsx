import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TapeStrip } from "@/components/flash/TapeStrip";
import type { TapeItem } from "@/components/flash/view";

/**
 * The premarket tape of 2026-09-03, verbatim. The point of the fixture is the
 * third tile: ow_spot returned a last price with no daily change, so the run
 * recorded none. The tile must SAY so — an intraday tile silently wearing the
 * premarket change is the one lie this page could tell that a reader has no
 * way to catch.
 */
const TAPE: TapeItem[] = [
  {
    label: "DFII10",
    value: "2.44%",
    change: "+12bp",
    source: "DFII10 10y real yield, 2026-09-01, ~2d behind",
  },
  {
    label: "VIX",
    value: "16.34",
    change: "+1.42",
    source: "VIXCLS, 14.92 on 08-31 → 16.34 on 09-01, ~2d behind",
  },
  {
    label: "SPY",
    value: "772.80",
    source: "ow_spot, last price only — no daily change recorded",
  },
];

describe("TapeStrip", () => {
  it("renders a change slot on every tile, recorded or not", () => {
    const { container } = render(<TapeStrip items={TAPE} />);

    expect(container.querySelectorAll("[data-testid='flash-tile']").length).toBe(
      3,
    );
    expect(container.querySelectorAll("[data-sign]").length).toBe(3);
  });

  it("prints an em dash, not a zero, when no change was recorded", () => {
    render(<TapeStrip items={TAPE} />);

    const spy = within(screen.getByTestId("flash-tile-SPY"));
    const slot = spy.getByLabelText("no change recorded");
    expect(slot.textContent).toBe("—");
    expect(slot.getAttribute("data-sign")).toBe("none");
  });

  it("takes the sign from the string the tenant wrote", () => {
    render(
      <TapeStrip
        items={[
          ...TAPE,
          { label: "AVGO", value: "355.90", change: "-10.87" },
        ]}
      />,
    );

    expect(
      within(screen.getByTestId("flash-tile-DFII10"))
        .getByText("+12bp")
        .getAttribute("data-sign"),
    ).toBe("pos");
    // A hyphen-minus is normalised to a real minus sign but stays negative.
    expect(
      within(screen.getByTestId("flash-tile-AVGO"))
        .getByText("−10.87")
        .getAttribute("data-sign"),
    ).toBe("neg");
  });

  it("puts provenance on the tile's title, never into the layout", () => {
    render(<TapeStrip items={TAPE} />);

    expect(screen.getByTestId("flash-tile-VIX").getAttribute("title")).toBe(
      "VIXCLS, 14.92 on 08-31 → 16.34 on 09-01, ~2d behind",
    );
    // The provenance string is not printed as its own line inside the tile.
    expect(
      within(screen.getByTestId("flash-tile-VIX")).queryByText(/VIXCLS/),
    ).toBeNull();
  });

  it("renders the sources line under the row when the run carried one", () => {
    const line =
      "Sources · SPY QQQ NVDA MSFT AVGO IWM — ow_spot, last price only, " +
      "the run recorded no daily change.";
    render(<TapeStrip items={TAPE} sourceLine={line} />);

    expect(screen.getByText(line)).toBeTruthy();
  });

  it("renders nothing at all when the run carried no tape", () => {
    const { container } = render(<TapeStrip items={[]} />);
    expect(container.innerHTML).toBe("");
  });
});
