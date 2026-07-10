import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { TechnicalsLiveResponse, TechnicalsResponse } from "@/lib/api";
import { mergeLiveHead } from "@/components/stock/tabs/TechnicalsTab";
import { TechnicalsKpiStrip } from "@/components/stock/panels/TechnicalsKpiStrip";

function freshLive(over: Partial<TechnicalsLiveResponse> = {}) {
  return {
    ticker: "MSFT",
    available: true,
    captured_at: new Date().toISOString(),
    spot: 105,
    spot_source: "xenon_ws",
    z: 0.3,
    z_band: "MILD HIGH",
    composite: 0.2,
    ...over,
  } as unknown as TechnicalsLiveResponse;
}

const base = {
  as_of: "2026-07-09",
  header: {
    price: 100,
    sma200: 90,
    z: -0.5,
    z_band: "MILD LOW",
    composite: 0.1,
  },
  series: [{ as_of: "2026-07-09", close: 100 }],
} as unknown as TechnicalsResponse;

describe("mergeLiveHead — price-card header", () => {
  it("consumes the live spot into price + z + dist_pct when fresh", () => {
    const m = mergeLiveHead(base, freshLive());
    expect(m.header?.price).toBe(105);
    expect(m.header?.z).toBe(0.3);
    expect(m.header?.z_band).toBe("MILD HIGH");
    expect(m.header?.dist_pct).toBeCloseTo(105 / 90 - 1, 6);
  });

  it("leaves the EOD header untouched when live is stale/absent", () => {
    const stale = freshLive({
      captured_at: new Date(Date.now() - 3_600_000).toISOString(),
    });
    expect(mergeLiveHead(base, stale).header?.price).toBe(100);
    expect(mergeLiveHead(base, null).header?.price).toBe(100);
  });
});

describe("TechnicalsKpiStrip — live marker", () => {
  it("shows a LIVE marker in the price card when fresh", () => {
    const { getByText } = render(
      <TechnicalsKpiStrip data={base} live={freshLive()} maxAgeSec={900} />,
    );
    expect(getByText("LIVE")).toBeTruthy();
  });

  it("shows EOD in the price card when there is no fresh live capture", () => {
    const { getByText } = render(
      <TechnicalsKpiStrip data={base} live={null} maxAgeSec={900} />,
    );
    expect(getByText("EOD")).toBeTruthy();
  });
});
