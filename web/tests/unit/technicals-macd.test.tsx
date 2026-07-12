import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  MacdLegend,
  macdSignal,
} from "@/components/stock/panels/TechnicalsPriceChart";

// Dual MACD now renders as a lightweight-charts sub-pane inside the price chart
// (canvas — not jsdom-renderable), so we test the pure signal/color classifier
// that drives the pane's directional badge, plus the (pure JSX) legend row.
//
// Backend trend_state ∈ {BULLISH, BEARISH, DETERIORATING, IMPROVING} — see
// cards/technicals.py dual_macd_state. There is no NEUTRAL state; the muted
// branch is a defensive fallback for unrecognized values only.
describe("macdSignal", () => {
  it("clean bull → full green, clean bear → full red", () => {
    expect(macdSignal({ trend_state: "BULLISH" })?.color).toBe(
      "var(--positive)",
    );
    expect(macdSignal({ trend_state: "BEARISH" })?.color).toBe(
      "var(--negative)",
    );
  });

  it("transitional states color by structure sign at a dimmed shade", () => {
    // DETERIORATING = bull structure cooling → dim green; IMPROVING = bear
    // structure recovering → dim red. Distinct from a clean trend.
    expect(macdSignal({ trend_state: "DETERIORATING" })?.color).toBe(
      "color-mix(in srgb, var(--positive) 55%, var(--text-muted))",
    );
    expect(macdSignal({ trend_state: "IMPROVING" })?.color).toBe(
      "color-mix(in srgb, var(--negative) 55%, var(--text-muted))",
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

  it("non-numeric confidence degrades to '—' (formatter guard), not a crash", () => {
    // detail.dual_macd is an untyped JSONB cast — confidence could drift.
    const s = macdSignal({
      tactical_signal: "DIP_BUY",
      confidence: "oops" as unknown as number,
    });
    expect(s?.text).toBe("DIP_BUY · conf —");
  });

  it("returns null when there is no signal at all", () => {
    expect(macdSignal(undefined)).toBeNull();
    expect(macdSignal({})).toBeNull();
  });

  it("unrecognized value → muted (defensive fallback)", () => {
    expect(macdSignal({ trend_state: "WAT" })?.color).toBe("var(--text-muted)");
  });
});

describe("MacdLegend", () => {
  it("renders the slow/fast structural/tactical labels", () => {
    render(<MacdLegend signal={null} />);
    expect(screen.getByText("SLOW 55/89/34 · structural")).toBeTruthy();
    expect(screen.getByText("FAST 13/21/9 · tactical")).toBeTruthy();
  });

  it("renders the directional badge uppercased with its signal color", () => {
    render(
      <MacdLegend signal={{ text: "bearish", color: "var(--negative)" }} />,
    );
    const badge = screen.getByTestId("technicals-macd-signal");
    expect(badge.textContent).toBe("BEARISH"); // uppercased in the badge
    expect(badge.style.color).toBe("var(--negative)");
  });

  it("omits the badge when there is no signal", () => {
    render(<MacdLegend signal={null} />);
    expect(screen.queryByTestId("technicals-macd-signal")).toBeNull();
  });
});
