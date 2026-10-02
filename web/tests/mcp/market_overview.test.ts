// market_overview: Columnar shape, verbatim card values, grid order,
// and the dashboardData split — /watchlist/chains failure degrades,
// /watchlist failure propagates.
import { describe, expect, test } from "vitest";
import type { Pool } from "pg";
import type { ToolCtx } from "@/mcp/types";
import { tool } from "@/mcp/tools/market_overview";
import { orderCards } from "@/lib/watchlist/cardOrder";
import watchlistFixture from "../fixtures/mcp/watchlist.json";
import chainsFixture from "../fixtures/mcp/watchlist_chains.json";

type Card = (typeof watchlistFixture.tickers)[number];

function stubCtx(
  handler: (path: string) => Promise<unknown> | unknown,
): { ctx: ToolCtx; calls: string[] } {
  const calls: string[] = [];
  return {
    calls,
    ctx: {
      db: null as unknown as Pool,
      tokenLabel: "test",
      apiGet: async (path: string) => {
        calls.push(path);
        return handler(path);
      },
    },
  };
}

const happyCtx = () =>
  stubCtx((path) => {
    if (path === "/watchlist") return watchlistFixture;
    if (path === "/watchlist/chains") return chainsFixture;
    throw new Error(`unexpected ${path}`);
  });

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const call = (ctx: ToolCtx) => tool.handler({}, ctx) as Promise<any>;

describe("market_overview", () => {
  test("shape: columnar fields plus chains, scheduler lag, and queue", async () => {
    const res = await call(happyCtx().ctx);
    expect(res.columns).toEqual([
      "ticker",
      "sector",
      "group",
      "chains",
      "pinned",
      "hot",
      "spot",
      "spot_quoted_at",
      "iv_atm",
      "iv_rank",
      "market_cap",
      "aum",
      "setup",
      "aggression_pct",
      "returns",
      "gamma",
      "skew",
      "positioning",
    ]);
    expect(res.rows).toHaveLength(watchlistFixture.tickers.length);
    expect(res.as_of).toEqual({
      eod: watchlistFixture.scanned_at_max,
      live: "2026-09-23T22:10:54+08:00",
    });
    expect(res.chains).toEqual(chainsFixture.chains);
    expect(res.chains_error).toBeUndefined();
    expect(res.scheduler_lag_seconds).toBe(
      watchlistFixture.scheduler_lag_seconds,
    );
    expect(res.queue).toEqual(watchlistFixture.queue);
  });

  test("row order equals orderCards on the same payload", async () => {
    const res = await call(happyCtx().ctx);
    const want = orderCards(
      watchlistFixture.tickers as never,
    ).map(({ card, group }) => [card.ticker, group]);
    expect(res.rows.map((r: unknown[]) => [r[0], r[2]])).toEqual(want);
  });

  test("card values pass through verbatim (first row = SPY)", async () => {
    const res = await call(happyCtx().ctx);
    const spy = watchlistFixture.tickers.find(
      (c: Card) => c.ticker === "SPY",
    )!;
    const row = res.rows[0];
    expect(row[0]).toBe("SPY");
    expect(row[6]).toBe(spy.spot); // spot verbatim — a string
    expect(row[7]).toBe(spy.spot_quoted_at);
    expect(row[14]).toEqual(spy.returns);
    expect(row[15]).toEqual(spy.gamma);
  });

  test("fetches watchlist and chains once each", async () => {
    const { ctx, calls } = happyCtx();
    await call(ctx);
    expect(calls.filter((p) => p === "/watchlist")).toHaveLength(1);
    expect(calls.filter((p) => p === "/watchlist/chains")).toHaveLength(1);
  });

  test("chains failure degrades to [] + chains_error", async () => {
    const res = await call(
      stubCtx((path) => {
        if (path === "/watchlist") return watchlistFixture;
        throw new Error("chains boom");
      }).ctx,
    );
    expect(res.chains).toEqual([]);
    expect(res.chains_error).toContain("chains boom");
    expect(res.rows).toHaveLength(watchlistFixture.tickers.length);
  });

  test("watchlist failure is the tool error", async () => {
    await expect(
      call(
        stubCtx((path) => {
          if (path === "/watchlist") throw new Error("watchlist boom");
          return chainsFixture;
        }).ctx,
      ),
    ).rejects.toThrow("watchlist boom");
  });
});
