import { describe, expect, it } from "vitest";
import { macdSignal } from "@/components/stock/panels/TechnicalsPriceChart";

// Dual MACD now renders as a lightweight-charts sub-pane inside the price chart
// (canvas — not jsdom-renderable), so we test the pure signal/color classifier
// that drives the pane's directional badge: bearish → red, bullish → green.
describe("macdSignal", () => {
  it("bullish trend → positive/green, bearish trend → negative/red", () => {
    expect(macdSignal({ trend_state: "BULLISH" })?.color).toBe(
      "var(--positive)",
    );
    expect(macdSignal({ trend_state: "BEARISH" })?.color).toBe(
      "var(--negative)",
    );
  });

  it("tactical signal wins over trend_state and carries confidence", () => {
    const s = macdSignal({
      trend_state: "BEARISH",
      tactical_signal: "DIP_BUY",
      confidence: 0.72,
    });
    expect(s?.text).toBe("DIP_BUY · conf 0.72");
    expect(s?.color).toBe("var(--positive)"); // DIP_BUY is a bullish action
  });

  it("RALLY_SELL is bearish → red; NONE falls back to trend_state", () => {
    expect(
      macdSignal({ tactical_signal: "RALLY_SELL", confidence: 0.5 })?.color,
    ).toBe("var(--negative)");
    const s = macdSignal({ tactical_signal: "NONE", trend_state: "BULLISH" });
    expect(s?.text).toBe("BULLISH");
    expect(s?.color).toBe("var(--positive)");
  });

  it("returns null when there is no signal at all", () => {
    expect(macdSignal(undefined)).toBeNull();
    expect(macdSignal({})).toBeNull();
  });

  it("unclassifiable trend → muted (neither green nor red)", () => {
    expect(macdSignal({ trend_state: "NEUTRAL" })?.color).toBe(
      "var(--text-muted)",
    );
  });
});
