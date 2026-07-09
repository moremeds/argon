import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { TechnicalsResponse } from "@/lib/api";
import { TechnicalsMacdChart } from "@/components/stock/panels/TechnicalsOscillators";

const data = {
  series: [
    { as_of: "2026-07-08", fast_macd_hist_atr: -0.4, slow_macd_hist_atr: 0.8 },
    { as_of: "2026-07-09", fast_macd_hist_atr: -0.2, slow_macd_hist_atr: 0.9 },
  ],
  detail: {
    dual_macd: {
      trend_state: "BULLISH",
      tactical_signal: "DIP_BUY",
      momentum_balance: "FAST_DOMINANT",
      confidence: 0.72,
    },
  },
} as unknown as TechnicalsResponse;

describe("TechnicalsMacdChart", () => {
  it("renders the dual-MACD title and tactical badge", () => {
    const { getAllByText, getByText } = render(
      <TechnicalsMacdChart data={data} />,
    );
    // Title renders in both the panel header and the SVG <title>.
    expect(getAllByText(/Dual MACD/i).length).toBeGreaterThan(0);
    // Badge headline is uniquely "DIP_BUY · conf 0.72" (DIP_BUY also appears
    // in the explanatory prose, so match the badge's signal+confidence shape).
    expect(getByText(/DIP_BUY · conf/)).toBeTruthy();
  });
});
