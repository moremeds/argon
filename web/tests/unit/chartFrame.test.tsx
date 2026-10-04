/* @vitest-environment jsdom */
// I-106 no-visual-change proof: static markup of the charts moved onto
// chartFrame(), rendered from a real API payload
// (tests/fixtures/mcp/aapl_volatility_series.json). Written BEFORE the move.
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { DivergenceOverlay } from "@/components/stock/panels/DivergenceOverlay";
import { HvIvChart } from "@/components/stock/panels/HvIvChart";
import { SmileChart } from "@/components/stock/panels/SmileChart";
import { TermStructureChart } from "@/components/stock/panels/TermStructureChart";
import type { components } from "@/lib/types";
import fixture from "@/tests/fixtures/mcp/aapl_volatility_series.json";

const series =
  fixture as unknown as components["schemas"]["VolatilitySeriesResponse"];

describe("I-106 chart markup (real AAPL volatility series)", () => {
  it.each([
    ["HvIvChart", () => <HvIvChart data={series.hv_iv_history} />],
    [
      "TermStructureChart",
      () => <TermStructureChart data={series.term_structure} />,
    ],
    [
      "DivergenceOverlay",
      () => (
        <DivergenceOverlay
          data={series.divergence}
          headline={series.divergence_headline}
        />
      ),
    ],
    [
      "HvIvChart (too short)",
      () => <HvIvChart data={series.hv_iv_history.slice(0, 1)} />,
    ],
    ["SmileChart", () => <SmileChart data={series.smile} spot={series.spot} />],
  ])("%s", (_name, el) => {
    expect(renderToStaticMarkup(el())).toMatchSnapshot();
  });
});
