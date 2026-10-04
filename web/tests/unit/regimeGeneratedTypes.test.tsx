/* @vitest-environment jsdom */
// I-103b no-change proof: static markup of every component that reads the
// useGex / useMarketTide response types, rendered from real API payloads
// (tests/fixtures/mcp/{spx_regime_gex,regime_market_tide}.json). Written BEFORE
// the hand-written types became aliases of the generated ones; the markup
// must not change.
import { renderToStaticMarkup } from "react-dom/server";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";

import gexFixture from "@/tests/fixtures/mcp/spx_regime_gex.json";
import tideFixture from "@/tests/fixtures/mcp/regime_market_tide.json";

vi.mock("@/lib/regime/useGex", async (orig) => ({
  ...(await orig<typeof import("@/lib/regime/useGex")>()),
  useGex: () => ({
    data: gexFixture,
    loading: false,
    syncing: false,
    error: null,
    lastSync: gexFixture.scan_time,
    syncNow: () => undefined,
  }),
}));
vi.mock("@/lib/regime/useMarketTide", async (orig) => ({
  ...(await orig<typeof import("@/lib/regime/useMarketTide")>()),
  useMarketTide: () => ({
    data: tideFixture,
    loading: false,
    syncing: false,
    error: null,
    lastSync: tideFixture.as_of,
    syncNow: () => undefined,
  }),
}));

import GexSubTab from "@/components/regime/GexSubTab";
import { HistoryChart } from "@/components/regime/HistoryChart";
import { MarketTideChart } from "@/components/regime/MarketTideChart";
import { MarketTideDailyChart } from "@/components/regime/MarketTideDailyChart";
import MarketTideSubTab from "@/components/regime/MarketTideSubTab";
import { TideSentimentBanner } from "@/components/regime/TideSentimentBanner";
import { ExpectedRangeBar } from "@/components/regime/gex/ExpectedRangeBar";
import { GexHistoryTable } from "@/components/regime/gex/GexHistoryTable";
import GexCurvatureChart from "@/components/shared/GexCurvatureChart";
import type { GexData } from "@/lib/regime/useGex";
import type { MarketTideData } from "@/lib/regime/useMarketTide";

const gex = gexFixture as unknown as GexData;
const tide = tideFixture as unknown as MarketTideData;
const sessions = tide.sessions ?? [];

beforeAll(() => {
  // The day after the fixtures' data date: freshness pills and staleness
  // checks read the clock.
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-09-24T14:00:00Z"));
});
afterAll(() => {
  vi.useRealTimers();
});

describe("I-103b markup snapshots (real SPX GEX and market-tide payloads)", () => {
  it.each([
    ["ExpectedRangeBar", () => <ExpectedRangeBar data={gex} />],
    ["GexHistoryTable", () => <GexHistoryTable history={gex.history ?? []} />],
    [
      "HistoryChart",
      () => <HistoryChart history={gex.history ?? []} ticker="SPX" />,
    ],
    [
      "GexCurvatureChart",
      () => (
        <GexCurvatureChart
          profile={gex.profile ?? []}
          spot={gex.spot as number}
        />
      ),
    ],
    ["MarketTideChart", () => <MarketTideChart data={tide} />],
    [
      "MarketTideDailyChart",
      () => (
        <MarketTideDailyChart
          session={sessions[sessions.length - 1] ?? null}
          spotTicker={tide.spot_ticker ?? "SPY"}
        />
      ),
    ],
    [
      "TideSentimentBanner",
      () => <TideSentimentBanner sentiment={tide.sentiment ?? null} />,
    ],
    ["GexSubTab", () => <GexSubTab />],
    ["MarketTideSubTab", () => <MarketTideSubTab />],
  ])("%s", (_name, el) => {
    expect(renderToStaticMarkup(el())).toMatchSnapshot();
  });
});
