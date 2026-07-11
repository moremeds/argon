import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { TechnicalsLiveResponse, TechnicalsResponse } from "@/lib/api";
import {
  etSessionDate,
  mergeLiveHead,
} from "@/components/stock/tabs/TechnicalsTab";
import { toCandleData } from "@/lib/priceChartData";
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

  it("advances the payload date to the live ET session when fresh", () => {
    // base as_of is 2026-07-09 (a settled prior session); a fresh live head
    // dates to today's ET session, which the Price tile must show.
    const today = etSessionDate(new Date().toISOString());
    const m = mergeLiveHead(base, freshLive());
    expect(m.as_of).toBe(today);
    expect(m.as_of! >= "2026-07-09").toBe(true); // only ever forward
  });

  it("leaves the EOD date when live is stale/absent", () => {
    const stale = freshLive({
      captured_at: new Date(Date.now() - 3_600_000).toISOString(),
    });
    expect(mergeLiveHead(base, stale).as_of).toBe("2026-07-09");
    expect(mergeLiveHead(base, null).as_of).toBe("2026-07-09");
  });

  it("leaves the EOD header untouched when live is stale/absent", () => {
    const stale = freshLive({
      captured_at: new Date(Date.now() - 3_600_000).toISOString(),
    });
    expect(mergeLiveHead(base, stale).header?.price).toBe(100);
    expect(mergeLiveHead(base, null).header?.price).toBe(100);
  });
});

// The chart's last-value price line always sits on the newest bar's close, so
// for it to track live the merged series head must carry the live spot as its
// close — then toCandleData renders that head as a flat candle at spot.
describe("mergeLiveHead — series head drives the live price line", () => {
  it("appends a live bar at the live spot for a new session", () => {
    const m = mergeLiveHead(base, freshLive({ spot: 105 }));
    const last = (m.series ?? []).at(-1)!;
    expect(last.close).toBe(105);
    const candle = toCandleData(m.series ?? []).at(-1) as { close?: number };
    expect(candle.close).toBe(105); // price line lands on the live spot
  });

  it("refreshes a provisional (close-only) same-day head with the live spot", () => {
    const today = etSessionDate(new Date().toISOString());
    const provisional = {
      ...base,
      series: [{ as_of: today, close: 100 }], // open == null -> provisional head
    } as unknown as TechnicalsResponse;
    const m = mergeLiveHead(provisional, freshLive({ spot: 107 }));
    expect((m.series ?? []).length).toBe(1); // refreshed in place, not appended
    expect((m.series ?? []).at(-1)!.close).toBe(107);
  });

  it("never clobbers a SETTLED same-day bar's close (keeps EOD intact)", () => {
    const today = etSessionDate(new Date().toISOString());
    const settled = {
      ...base,
      series: [{ as_of: today, open: 99, high: 101, low: 98, close: 100 }],
    } as unknown as TechnicalsResponse;
    const m = mergeLiveHead(settled, freshLive({ spot: 107 }));
    expect((m.series ?? []).length).toBe(1);
    expect((m.series ?? []).at(-1)!.close).toBe(100); // settled close untouched
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
