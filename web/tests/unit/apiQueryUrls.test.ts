// I-104 wire proof: the exact URL every query-building `api.*` method sends.
// The snapshot was written BEFORE the query builder replaced the hand-built
// strings; the refactor must leave it unchanged.
import { afterEach, expect, it, vi } from "vitest";

import { api } from "@/lib/api";

afterEach(() => {
  vi.unstubAllGlobals();
});

it("query-string URLs are unchanged", async () => {
  const urls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      urls.push(String(url));
      return new Response("{}", { status: 200 });
    }),
  );
  const calls: (() => Promise<unknown>)[] = [
    () => api.cockpitState("SPY", "2026-05-15"),
    () => api.cockpitState("SPY"),
    () => api.cockpitState("SPY", ""),
    () => api.cockpitDealer("SPY", "2026-05-15"),
    () => api.cockpitSurface("SPY", "2026-05-15"),
    () => api.cockpitFlowIm("SPY", "2026-05-15"),
    () => api.cockpitVrp("SPY", "2026-05-15"),
    () => api.cockpitVrp("SPY"),
    () => api.goldInputSeries("DFII10"),
    () =>
      api.goldInputSeries("DFII10", {
        from: "2026-01-01",
        to: "2026-02-01",
        asOf: "2026-02-02",
      }),
    () => api.goldInputSeries("DFII10", { from: "", asOf: "2026-02-02" }),
    () => api.radar(),
    () => api.radar({ tier: "", limit: 0, min_dimensions: 3 }),
    () =>
      api.radar({
        tier: "A",
        engine_version: "v2&x=1",
        limit: 50,
        min_dimensions: 0,
      }),
    () => api.chainMatrix(),
    () =>
      api.chainMatrix({
        taxonomy_version: "t1",
        engine_version: "e1",
        domain: "ai/semi",
      }),
    () => api.chainMembers("AI chips/HBM"),
    () => api.chainMembers("x&y", { layer: "memory", engine_version: "e1" }),
    () => api.health(),
    () =>
      api.health("massive", { recordWindowHours: 0, recordMinCoverage: 0.9 }),
    () => api.assembleResearchReport("company", "AAPL", "2026-05-15"),
    () => api.assembleResearchReport("company", "AAPL"),
    () => api.companyDimensions("AAPL"),
    () => api.companyDimensions("AAPL", "fund-v2/b"),
    () => api.regimeGex("BRK.B"),
    () => api.regimeDealer("SPX"),
    () => api.vrpBacktest(),
    () => api.vrpBacktest(0),
    () => api.deskDelta("ai-semi"),
    () => api.deskDelta("ai-semi", "2026-05-01"),
    () => api.researchReports(),
    () => api.healthBenchmarkHistory(),
    () => api.agentRunWeeks("flash"),
    () => api.agentRunWeek("flash", "2026-W20"),
    () => api.agentRun("flash", "daily", "2026-05-15"),
    () => api.agentRun("fl&sh", "daily", "2026-05-15", 0),
    () => api.agentRunLatest("flash"),
    () => api.agentRunLatest("flash", "a b"),
  ];
  for (const c of calls) await c();
  expect(urls).toMatchSnapshot();
});
