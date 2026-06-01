/* @vitest-environment jsdom */
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ScanAllButton } from "@/components/shared/ScanAllButton";
import { QueueProgress } from "@/components/shared/QueueProgress";
import { AddTickerDialog } from "@/components/watchlist/AddTickerDialog";
import { TickerCard } from "@/components/watchlist/TickerCard";
import { api } from "@/lib/api";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn() }),
}));

vi.mock("@/lib/api", () => ({
  api: {
    watchlist: vi.fn(),
    queueSummary: vi.fn(),
    rescan: vi.fn(),
    rescanAll: vi.fn(),
    job: vi.fn(),
    patchTicker: vi.fn(),
  },
}));

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.mocked(api.watchlist).mockReset();
  vi.mocked(api.queueSummary).mockReset();
  vi.mocked(api.rescan).mockReset();
  vi.mocked(api.rescanAll).mockReset();
  vi.mocked(api.job).mockReset();
  vi.mocked(api.patchTicker).mockReset();
});

function installDialogPolyfill() {
  HTMLDialogElement.prototype.showModal = function showModal() {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function close() {
    this.open = false;
  };
}

const card = {
  ticker: "TSLA",
  sector: "Technology",
  pinned: false,
  sort_rank: 0,
  spot: "445.12",
  spot_quoted_at: "2026-05-14T00:54:48Z",
  spot_source: "massive.com_intraday",
  scanned_at: "2026-05-14T00:44:48Z",
  iv_atm: "0.691",
  iv_rank: "39.0",
  setup: { type: "C", direction: "bear", score: "1.51" },
  aggression_pct: "0.91",
  returns: { d1: "0.01", w1: "0.02", d30: "-0.03" },
  gamma: {
    flip_distance: "0.05",
    flip_price: "420",
    per_1pct_move: "1000",
    max_strike: "450",
    expiring_pct: "0.20",
    expiring_date: "2026-05-15",
  },
  skew: { rr25d_30dte: "-0.0146" },
  positioning: {
    call_oi: 1200000,
    put_oi: 2100000,
    pcr_oi: "1.75",
    pcr_vol: "1.58",
    pcr_delta_30d: "-0.03",
  },
};

describe("TickerCard", () => {
  it("shows full quoted and analytics timestamps with timezone", () => {
    render(<TickerCard card={card} sparkline={[440, 445]} />);

    expect(screen.getByText(/spot /).textContent).toMatch(
      /2026.*\d{2}:\d{2}:\d{2}.*(?:UTC|GMT|[A-Z]{2,5})/,
    );
    expect(screen.getByText(/analytics /).textContent).toMatch(
      /2026.*\d{2}:\d{2}:\d{2}.*(?:UTC|GMT|[A-Z]{2,5})/,
    );
  });

  it("renders timestamps as compact card metadata", () => {
    render(<TickerCard card={card} sparkline={[440, 445]} />);

    const timestampBlock = screen.getByText(/spot /).parentElement;

    expect(timestampBlock).toHaveProperty("style.fontSize", "8px");
  });

  it("shows an in-place not-ready popup for an unscanned ticker", () => {
    render(
      <TickerCard
        card={{ ...card, ticker: "SOXX", scanned_at: null }}
        sparkline={[]}
      />,
    );

    expect(screen.queryByRole("link", { name: /soxx detail/i })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /soxx detail/i }));

    expect(screen.getByText("SOXX is not ready")).not.toBeNull();
  });

  it("shows active queue status on the card", () => {
    render(
      <TickerCard
        card={{
          ...card,
          queue: {
            job_id: "00000000-0000-0000-0000-000000000001",
            status: "queued",
            queue_position: 4,
            requested_at: "2026-05-16T00:13:17Z",
            started_at: null,
          },
        }}
        sparkline={[440, 445]}
      />,
    );

    expect(screen.getByText("queued #4")).not.toBeNull();
  });

  it("fetches OHLC client-side when no sparkline prop is supplied", async () => {
    const ac: AbortSignal[] = [];
    const fetchMock = vi.fn(
      (_url: string, init?: { signal?: AbortSignal }): Promise<Response> => {
        if (init?.signal) ac.push(init.signal);
        return Promise.resolve(
          new Response(
            JSON.stringify([
              {
                date: "2026-05-12",
                close: "200",
                open: null,
                high: null,
                low: null,
                volume: null,
              },
              {
                date: "2026-05-13",
                close: "210",
                open: null,
                high: null,
                low: null,
                volume: null,
              },
            ]),
            { status: 200 },
          ),
        );
      },
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<TickerCard card={card} />);

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/ohlc/TSLA?days=30",
        expect.objectContaining({ cache: "no-store" }),
      );
    });
    // SVG path is populated once closes state is set from the fetched bars.
    await waitFor(() => {
      const path = document.querySelector("svg path");
      expect(path?.getAttribute("d")).toBeTruthy();
    });
  });

  it("does not fetch when the ticker has not been scanned", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    render(<TickerCard card={{ ...card, scanned_at: null }} />);

    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("QueueProgress", () => {
  it("shows running and queued rescan progress", () => {
    render(
      <QueueProgress
        queue={{
          total: 8,
          queued: 6,
          running: 2,
          oldest_requested_at: "2026-05-16T00:13:17Z",
        }}
      />,
    );

    const progress = screen.getByRole("progressbar", {
      name: /rescan queue/i,
    });
    expect(progress.getAttribute("aria-valuenow")).toBe("2");
    expect(progress.getAttribute("aria-valuemax")).toBe("8");
    expect(screen.getByText("2 running · 6 queued")).not.toBeNull();
  });

  it("discovers queue work that starts after the dashboard loaded idle", async () => {
    vi.useFakeTimers();
    vi.mocked(api.queueSummary).mockResolvedValueOnce({
      total: 1,
      queued: 1,
      running: 0,
      oldest_requested_at: "2026-05-16T00:13:17Z",
    });

    render(
      <QueueProgress
        queue={{
          total: 0,
          queued: 0,
          running: 0,
          oldest_requested_at: null,
        }}
      />,
    );

    expect(screen.getByText("idle")).not.toBeNull();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });

    expect(api.queueSummary).toHaveBeenCalledOnce();
    expect(api.watchlist).not.toHaveBeenCalled();
    expect(screen.getByText("0 running · 1 queued")).not.toBeNull();

    vi.useRealTimers();
  });
});

describe("AddTickerDialog", () => {
  it("uses the current dashboard sector grouping in the sector menu", () => {
    installDialogPolyfill();
    render(<AddTickerDialog />);

    fireEvent.click(screen.getByRole("button", { name: /\+ ticker/i }));

    expect(screen.queryByRole("combobox")).toBeNull();
    expect(screen.getByRole("button", { name: /sector etf/i })).not.toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /sector etf/i }));

    expect(screen.getByText("Index")).not.toBeNull();
    expect(screen.getByText("AI/Tech")).not.toBeNull();
    expect(screen.getByText("Thematic")).not.toBeNull();
    expect(screen.getByText("Defensive")).not.toBeNull();
    expect(screen.getByRole("option", { name: "ETF" })).not.toBeNull();
    expect(screen.getByRole("option", { name: "M7" })).not.toBeNull();
    expect(screen.getByRole("option", { name: "NeoCloud" })).not.toBeNull();
    expect(screen.getByRole("option", { name: "Power" })).not.toBeNull();
    expect(screen.getByRole("option", { name: "Airlines" })).not.toBeNull();
    expect(screen.queryByRole("option", { name: "Technology" })).toBeNull();
    expect(screen.queryByRole("option", { name: "All" })).toBeNull();

    fireEvent.click(screen.getByRole("option", { name: "Power" }));

    expect(
      screen.getByRole("button", { name: /sector power/i }),
    ).not.toBeNull();
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("closes when the backdrop is clicked", () => {
    installDialogPolyfill();
    render(<AddTickerDialog />);

    fireEvent.click(screen.getByRole("button", { name: /\+ ticker/i }));
    const dialog = screen.getByRole("dialog", { name: /add ticker/i });
    expect(dialog).toHaveProperty("open", true);

    fireEvent.click(dialog);

    expect(dialog).toHaveProperty("open", false);
  });
});

describe("ScanAllButton", () => {
  it("opens a confirmation dialog before enqueueing a watchlist scan", () => {
    installDialogPolyfill();
    render(<ScanAllButton />);

    fireEvent.click(screen.getByRole("button", { name: /scan all/i }));

    expect(screen.getByRole("dialog", { name: /scan all/i })).toHaveProperty(
      "open",
      true,
    );
    expect(api.rescanAll).not.toHaveBeenCalled();
  });

  it("does not enqueue a watchlist scan when the confirmation is cancelled", () => {
    installDialogPolyfill();
    render(<ScanAllButton />);

    fireEvent.click(screen.getByRole("button", { name: /scan all/i }));
    fireEvent.click(screen.getByRole("button", { name: /cancel/i }));

    expect(api.rescanAll).not.toHaveBeenCalled();
  });

  it("enqueues a watchlist scan after dialog confirmation", async () => {
    installDialogPolyfill();
    vi.mocked(api.rescanAll).mockResolvedValue([]);
    render(<ScanAllButton />);

    fireEvent.click(screen.getByRole("button", { name: /scan all/i }));
    fireEvent.click(screen.getByRole("button", { name: /confirm scan all/i }));

    await waitFor(() => {
      expect(api.rescanAll).toHaveBeenCalledOnce();
    });
  });
});
