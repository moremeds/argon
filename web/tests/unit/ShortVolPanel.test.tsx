/* @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ShortVolPanel } from "@/components/stock/panels/ShortVolPanel";
import type { components } from "@/lib/types";

type Report = components["schemas"]["SingleStockReport"];

// Real TSLA 2026-06-24 spot; short_vol shaped like the serialized API response
// (Decimal → string).
const base = { ticker: "TSLA" } as unknown as Report;
const withShortVol = (sv: unknown): Report =>
  ({ ...base, short_vol: sv }) as Report;

const tradeSv = {
  as_of: "2026-06-24",
  basis: "eod",
  action: "TRADE",
  skip_reason: null,
  spot: "382.35",
  iv: "0.473",
  rv20: "0.40",
  vrp: "0.073",
  vrp_z: "1.6",
  weight: "1",
  short_put: "360",
  long_put: "340",
  put_width: "20",
  credit: "4.2",
  max_loss: "15.8",
  hold_days: 30,
  short_delta: "0.25",
  wing_delta: "0.125",
};

const skipSv = {
  ...tradeSv,
  action: "SKIP",
  skip_reason: "sector vol not sellable",
  weight: "0",
  short_put: null,
  long_put: null,
  put_width: null,
  credit: null,
  max_loss: null,
};

describe("ShortVolPanel", () => {
  it("renders TRADE with spread strikes and the bull-put footer", () => {
    render(<ShortVolPanel report={withShortVol(tradeSv)} />);
    expect(screen.getByTestId("short-vol-action").textContent).toBe("TRADE");
    expect(screen.getByText(/Sell 360 \/ buy 340 put/)).toBeTruthy();
    expect(
      screen.getByText(/Bull put spread 0\.25Δ\/0\.125Δ · ~30d hold/),
    ).toBeTruthy();
    // [5] as_of surfaces in the badge so a stale row is visible
    expect(screen.getByText("EOD · 2026-06-24")).toBeTruthy();
    // [8] the structurally-pinned weight tile is gone
    expect(screen.queryByText(/weight/i)).toBeNull();
    // [3] modeled EOD spot basis is shown so strikes aren't read vs the live header
    expect(screen.getByText(/spot 382\.35/)).toBeTruthy();
  });

  it("renders SKIP with the reason and IV/RV", () => {
    render(<ShortVolPanel report={withShortVol(skipSv)} />);
    expect(screen.getByTestId("short-vol-action").textContent).toBe("SKIP");
    expect(screen.getByText("sector vol not sellable")).toBeTruthy();
    expect(screen.getByText(/IV 47\.3% \/ RV20 40\.0%/)).toBeTruthy();
  });

  it("renders a no-data state when short_vol is null", () => {
    render(<ShortVolPanel report={withShortVol(null)} />);
    expect(screen.getByTestId("short-vol-panel")).toBeTruthy();
    expect(screen.getByText(/No vol data/)).toBeTruthy();
  });
});
