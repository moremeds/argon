/* @vitest-environment jsdom */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DiscoveredCard } from "@/components/scanner/DiscoveredCard";
import { api } from "@/lib/api";
import type { components } from "@/lib/types";

type Discovered = components["schemas"]["DiscoveryCandidate"];

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn() }),
}));

vi.mock("@/lib/api", () => ({
  api: {
    addTicker: vi.fn(),
    rescan: vi.fn(),
  },
}));

afterEach(() => {
  vi.clearAllMocks();
});

function makeDiscovered(overrides: Partial<Discovered> = {}): Discovered {
  return {
    ticker: "GFS",
    bias: "bullish",
    bias_strength: "moderate",
    alert_count: 4,
    sector: "Technology",
    latest_alert_at: new Date(Date.now() - 15 * 60_000).toISOString(),
    hit: {
      signal_type: "deep_conviction_flow",
      tier: 1,
      score: "0.85" as unknown as Discovered["hit"]["score"],
      evidence: {
        direction: "long",
        total_premium: "1500000",
        qualifying_alerts: 4,
        top_strike: "55",
        top_option_type: "call",
        top_expiry: "2026-09-18",
        top_ask_side_ratio: "0.92",
      },
      freshness: "live",
    },
    ...overrides,
  };
}

describe("DiscoveredCard", () => {
  it("renders ticker, sector, signal row, and DISCOVERED badge", () => {
    render(<DiscoveredCard candidate={makeDiscovered()} />);

    expect(screen.getByText("GFS")).toBeTruthy();
    expect(screen.getByText("Technology")).toBeTruthy();
    expect(screen.getByText(/Conviction Flow/i)).toBeTruthy();
    expect(screen.getByText("DISCOVERED")).toBeTruthy();
  });

  it("uses bias-tinted color on the ticker", () => {
    render(<DiscoveredCard candidate={makeDiscovered()} />);
    const ticker = screen.getByText("GFS");
    expect((ticker as HTMLElement).style.color).toContain("--positive");
  });

  it("shows alert count and last-seen in the footer", () => {
    render(<DiscoveredCard candidate={makeDiscovered()} />);
    // "4 alerts" also appears in the SignalRow line — match the footer's combined
    // "N alerts · last … ago" string instead.
    expect(screen.getByText(/4 alerts · last 15m ago/)).toBeTruthy();
  });

  it("explains the badge via title attribute", () => {
    render(<DiscoveredCard candidate={makeDiscovered()} />);
    const badge = screen.getByText("DISCOVERED");
    expect(badge.getAttribute("title")).toMatch(/market-wide flow-alerts/i);
  });

  it("+ Watchlist button calls addTicker then rescan with the ticker's sector", async () => {
    vi.mocked(api.addTicker).mockResolvedValue({ ok: true, ticker: "GFS" });
    vi.mocked(api.rescan).mockResolvedValue({
      job_id: "j1",
      status: "queued",
    } as unknown as Awaited<ReturnType<typeof api.rescan>>);

    render(<DiscoveredCard candidate={makeDiscovered()} />);
    fireEvent.click(screen.getByRole("button", { name: /Add GFS/i }));

    await waitFor(() => {
      expect(api.addTicker).toHaveBeenCalledWith({
        ticker: "GFS",
        sector: "Technology",
        notes: expect.stringMatching(/discovery/i),
      });
      expect(api.rescan).toHaveBeenCalledWith("GFS");
    });
    expect(await screen.findByText("✓ added")).toBeTruthy();
  });

  it("falls back to 'Unknown' sector when none is provided", async () => {
    vi.mocked(api.addTicker).mockResolvedValue({ ok: true, ticker: "XYZ" });
    vi.mocked(api.rescan).mockResolvedValue({
      job_id: "j2",
      status: "queued",
    } as unknown as Awaited<ReturnType<typeof api.rescan>>);

    render(
      <DiscoveredCard
        candidate={makeDiscovered({ ticker: "XYZ", sector: null })}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Add XYZ/i }));

    await waitFor(() => {
      expect(api.addTicker).toHaveBeenCalledWith({
        ticker: "XYZ",
        sector: "Unknown",
        notes: expect.any(String),
      });
    });
  });

  it("shows ✗ failed when addTicker rejects, does not call rescan", async () => {
    vi.mocked(api.addTicker).mockRejectedValue(new Error("conflict"));

    render(<DiscoveredCard candidate={makeDiscovered()} />);
    fireEvent.click(screen.getByRole("button", { name: /Add GFS/i }));

    expect(await screen.findByText("✗ failed")).toBeTruthy();
    expect(api.rescan).not.toHaveBeenCalled();
  });
});
