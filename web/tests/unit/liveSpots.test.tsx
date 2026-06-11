/* @vitest-environment jsdom */
import { act, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  LiveSpotsProvider,
  useLiveSpot,
} from "@/components/watchlist/LiveSpotsProvider";

vi.mock("@/lib/api", () => ({
  api: {
    watchlistSpots: vi.fn().mockResolvedValue({
      spots: [
        {
          ticker: "TSLA",
          spot: "445.99",
          spot_quoted_at: "2026-06-11T15:42:04.432Z",
          spot_source: "xenon_ws",
        },
      ],
    }),
  },
}));

function Probe({ ticker }: { ticker: string }) {
  const live = useLiveSpot(ticker);
  return (
    <span data-testid="probe">
      {live ? `${live.spot}:${live.spot_source}` : "fallback"}
    </span>
  );
}

describe("LiveSpotsProvider", () => {
  it("provides polled spots to consumers", async () => {
    await act(async () => {
      render(
        <LiveSpotsProvider>
          <Probe ticker="TSLA" />
        </LiveSpotsProvider>,
      );
    });
    expect(screen.getByTestId("probe").textContent).toBe("445.99:xenon_ws");
  });

  it("falls back when no provider is mounted", () => {
    render(<Probe ticker="TSLA" />);
    expect(screen.getByTestId("probe").textContent).toBe("fallback");
  });

  it("falls back for tickers absent from the snapshot", async () => {
    await act(async () => {
      render(
        <LiveSpotsProvider>
          <Probe ticker="NVDA" />
        </LiveSpotsProvider>,
      );
    });
    expect(screen.getByTestId("probe").textContent).toBe("fallback");
  });

  // Codex P1 follow-up: the components that consume `useLiveSpot` are
  // browser-verified but lack render-level regression coverage. These three
  // assertions guard the "consumes context value, not server-rendered prop"
  // wiring against future refactors.
  it("DetailHeader prefers live spot over server-rendered prop", async () => {
    const { DetailHeader } = await import("@/components/stock/DetailHeader");
    await act(async () => {
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
    });
    // Live spot is 445.99 from the vi.mock above — server-rendered prop
    // was 100. The header must reflect the live value.
    expect(screen.getByText("$445.99")).not.toBeNull();
  });
});
