/* @vitest-environment jsdom */
// I-107 behavior proof: each poller moved onto usePolledResource keeps its own
// cadence, hidden-tab/in-flight skipping and error handling. Written against
// the hand-rolled pollers BEFORE the move; it must pass unchanged after it.
import { act, render, renderHook, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const spots = vi.fn();
const technicals = vi.fn();
const technicalsLive = vi.fn();
vi.mock("@/lib/api", () => ({
  api: {
    watchlistSpots: (...a: unknown[]) => spots(...a),
    technicals: (...a: unknown[]) => technicals(...a),
    technicalsLive: (...a: unknown[]) => technicalsLive(...a),
    technicalsRefresh: vi.fn(),
  },
}));
vi.mock("@/components/stock/panels/TechnicalsPriceChart", () => ({
  TechnicalsPriceChart: () => <div data-testid="price-chart" />,
}));

import {
  LiveSpotsProvider,
  useLiveSpot,
} from "@/components/watchlist/LiveSpotsProvider";
import { TechnicalsTab } from "@/components/stock/tabs/TechnicalsTab";
import { useDispersion } from "@/lib/regime/useDispersion";

const flush = () => act(async () => {});
const tick = (ms: number) => act(() => vi.advanceTimersByTimeAsync(ms));

beforeEach(() => {
  vi.useFakeTimers();
  spots.mockReset();
  technicals.mockReset();
  technicalsLive.mockReset();
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  Object.defineProperty(document, "hidden", {
    value: false,
    configurable: true,
  });
});

describe("useDispersion", () => {
  it("fetches on mount, every 5 min, and keeps the last value on error", async () => {
    let n = 0;
    const fetchMock = vi.fn(async () => {
      n += 1;
      if (n === 2) return new Response("boom", { status: 500 });
      return new Response(JSON.stringify({ n }), { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);
    const { result, unmount } = renderHook(() => useDispersion());
    await flush();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(result.current).toEqual({ n: 1 });
    await tick(5 * 60 * 1000 - 1);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await tick(1);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(result.current).toEqual({ n: 1 }); // error keeps the last value
    await tick(5 * 60 * 1000);
    expect(result.current).toEqual({ n: 3 });
    unmount();
    await tick(10 * 60 * 1000);
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });
});

function Probe() {
  const s = useLiveSpot("TSLA");
  return <span data-testid="spot">{s ? String(s.spot) : "none"}</span>;
}

describe("LiveSpotsProvider", () => {
  it("polls every 2.5 s, skips hidden tabs and in-flight requests, keeps the map on error", async () => {
    let n = 0;
    spots.mockImplementation(async () => {
      n += 1;
      return { spots: [{ ticker: "TSLA", spot: String(n) }] };
    });
    render(
      <LiveSpotsProvider>
        <Probe />
      </LiveSpotsProvider>,
    );
    await flush();
    expect(spots).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("spot").textContent).toBe("1");
    await tick(2499);
    expect(spots).toHaveBeenCalledTimes(1);
    await tick(1);
    expect(spots).toHaveBeenCalledTimes(2);

    Object.defineProperty(document, "hidden", {
      value: true,
      configurable: true,
    });
    await tick(2500 * 3);
    expect(spots).toHaveBeenCalledTimes(2);
    Object.defineProperty(document, "hidden", {
      value: false,
      configurable: true,
    });

    spots.mockImplementationOnce(async () => {
      throw new Error("down");
    });
    await tick(2500);
    expect(spots).toHaveBeenCalledTimes(3);
    expect(screen.getByTestId("spot").textContent).toBe("2");

    let release: (v: unknown) => void = () => undefined;
    spots.mockImplementationOnce(() => new Promise((r) => (release = r)));
    await tick(2500); // starts the request that hangs
    await tick(2500 * 2); // in flight: both ticks skip
    expect(spots).toHaveBeenCalledTimes(4);
    await act(async () => release({ spots: [{ ticker: "TSLA", spot: "9" }] }));
    expect(screen.getByTestId("spot").textContent).toBe("9");
    await tick(2500);
    expect(spots).toHaveBeenCalledTimes(5);
  });
});

describe("TechnicalsTab live head", () => {
  it("polls every 25 s and restarts per ticker", async () => {
    technicals.mockResolvedValue({
      ticker: "NVDA",
      backfill_status: "ready",
      as_of: "2026-07-09",
      header: {},
      series: [
        {
          as_of: "2026-07-09",
          close: 101,
          open: 99,
          high: 102,
          low: 98,
          volume: 5,
        },
      ],
      detail: {},
      forward_returns: [],
      vwap_anchor: null,
    });
    technicalsLive.mockResolvedValue({ ticker: "NVDA", available: false });
    const { rerender } = render(<TechnicalsTab ticker="NVDA" />);
    await flush();
    expect(technicalsLive).toHaveBeenCalledTimes(1);
    expect(technicalsLive).toHaveBeenLastCalledWith("NVDA");
    await tick(24_999);
    expect(technicalsLive).toHaveBeenCalledTimes(1);
    await tick(1);
    expect(technicalsLive).toHaveBeenCalledTimes(2);
    rerender(<TechnicalsTab ticker="AMD" />);
    await flush();
    expect(technicalsLive).toHaveBeenCalledTimes(3);
    expect(technicalsLive).toHaveBeenLastCalledWith("AMD");
    await tick(25_000);
    expect(technicalsLive).toHaveBeenCalledTimes(4);
  });
});
