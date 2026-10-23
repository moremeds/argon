/* @vitest-environment jsdom */
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  LiveSpotsProvider,
  SPOTS_STREAM_PATH,
  useLiveSpot,
} from "@/components/watchlist/LiveSpotsProvider";

// jsdom has no EventSource: a stand-in the test drives by hand.
class FakeEventSource {
  static readonly CLOSED = 2;
  static instances: FakeEventSource[] = [];
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  listeners = new Map<string, () => void>();
  readyState = 1;
  closed = false;
  constructor(public url: string) {
    FakeEventSource.instances.push(this);
  }
  addEventListener(type: string, fn: () => void) {
    this.listeners.set(type, fn);
  }
  close() {
    this.closed = true;
    this.readyState = FakeEventSource.CLOSED;
  }
  ping() {
    act(() => this.listeners.get("ping")?.());
  }
  emit(spots: object[]) {
    act(() => {
      this.onmessage?.(
        new MessageEvent("message", { data: JSON.stringify({ spots }) }),
      );
    });
  }
}

const latest = () => FakeEventSource.instances.at(-1)!;
const setHidden = (hidden: boolean) => {
  Object.defineProperty(document, "hidden", {
    configurable: true,
    value: hidden,
  });
  act(() => {
    document.dispatchEvent(new Event("visibilitychange"));
  });
};

const TSLA = {
  ticker: "TSLA",
  spot: "445.99",
  spot_quoted_at: "2026-06-11T15:42:04.432Z",
  spot_source: "xenon_ws",
};

function Probe({ ticker }: { ticker: string }) {
  const live = useLiveSpot(ticker);
  return (
    <span data-testid={`probe-${ticker}`}>
      {live ? `${live.spot}:${live.spot_source}` : "fallback"}
    </span>
  );
}

beforeEach(() => {
  FakeEventSource.instances = [];
  vi.stubGlobal("EventSource", FakeEventSource);
  Object.defineProperty(document, "hidden", {
    configurable: true,
    value: false,
  });
});
afterEach(() => {
  vi.unstubAllGlobals();
});

describe("LiveSpotsProvider", () => {
  it("opens one stream and provides pushed spots to consumers", () => {
    render(
      <LiveSpotsProvider>
        <Probe ticker="TSLA" />
      </LiveSpotsProvider>,
    );
    expect(FakeEventSource.instances).toHaveLength(1);
    expect(latest().url).toBe(SPOTS_STREAM_PATH);
    expect(screen.getByTestId("probe-TSLA").textContent).toBe("fallback");
    latest().emit([TSLA]);
    expect(screen.getByTestId("probe-TSLA").textContent).toBe(
      "445.99:xenon_ws",
    );
  });

  it("merges change-only events into the map", () => {
    render(
      <LiveSpotsProvider>
        <Probe ticker="TSLA" />
        <Probe ticker="NVDA" />
      </LiveSpotsProvider>,
    );
    latest().emit([TSLA, { ...TSLA, ticker: "NVDA", spot: "181.2" }]);
    latest().emit([{ ...TSLA, spot: "446.10" }]); // NVDA unchanged, not resent
    expect(screen.getByTestId("probe-TSLA").textContent).toBe(
      "446.10:xenon_ws",
    );
    expect(screen.getByTestId("probe-NVDA").textContent).toBe("181.2:xenon_ws");
  });

  it("falls back when no provider is mounted", () => {
    render(<Probe ticker="TSLA" />);
    expect(screen.getByTestId("probe-TSLA").textContent).toBe("fallback");
  });

  it("closes the stream while hidden and reopens when shown", () => {
    const { unmount } = render(
      <LiveSpotsProvider>
        <span />
      </LiveSpotsProvider>,
    );
    const first = latest();
    setHidden(true);
    expect(first.closed).toBe(true);
    setHidden(false);
    expect(FakeEventSource.instances).toHaveLength(2);
    unmount();
    expect(latest().closed).toBe(true);
  });

  it("watchdog reopens a stream the browser gave up on", () => {
    vi.useFakeTimers();
    render(
      <LiveSpotsProvider>
        <Probe ticker="TSLA" />
      </LiveSpotsProvider>,
    );
    latest().emit([TSLA]);
    latest().readyState = FakeEventSource.CLOSED; // re-dial got a proxy 5xx
    act(() => vi.advanceTimersByTime(1000));
    expect(FakeEventSource.instances).toHaveLength(2);
    latest().emit([{ ...TSLA, spot: "446.10" }]);
    expect(screen.getByTestId("probe-TSLA").textContent).toBe(
      "446.10:xenon_ws",
    );
    vi.useRealTimers();
  });

  it("watchdog reopens a silent stream; pings keep a live one", () => {
    vi.useFakeTimers();
    render(
      <LiveSpotsProvider>
        <span />
      </LiveSpotsProvider>,
    );
    for (let i = 0; i < 5; i++) {
      act(() => vi.advanceTimersByTime(2000));
      latest().ping();
    }
    expect(FakeEventSource.instances).toHaveLength(1); // 10 s alive on pings
    act(() => vi.advanceTimersByTime(6000)); // half-open: nothing arrives
    expect(FakeEventSource.instances).toHaveLength(2);
    expect(FakeEventSource.instances[0].closed).toBe(true);
    vi.useRealTimers();
  });

  // Codex P1 follow-up: guards the "consumes context value, not
  // server-rendered prop" wiring of a useLiveSpot consumer.
  it("DetailHeader prefers live spot over server-rendered prop", async () => {
    const { DetailHeader } = await import("@/components/stock/DetailHeader");
    render(
      <LiveSpotsProvider>
        <DetailHeader
          ticker="TSLA"
          spot={100}
          iv_atm={0.5}
          spotQuotedAt={null}
          scannedAt={null}
          setupType={null}
          setupDirection={null}
          setupScore={null}
        />
      </LiveSpotsProvider>,
    );
    latest().emit([TSLA]);
    expect(screen.getByText("$445.99")).not.toBeNull();
  });
});
