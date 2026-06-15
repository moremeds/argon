/* @vitest-environment jsdom */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DiscoveredCard } from "@/components/scanner/DiscoveredCard";
import { api } from "@/lib/api";
import type { components } from "@/lib/types";

type Discovered = components["schemas"]["DiscoveryCandidate"];
const NOW_MS = Date.parse("2026-06-15T14:30:00Z");

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
    ticker: "ZAAA",
    bias: "bullish",
    bias_strength: "moderate",
    direction: "long",
    score: "78.5" as unknown as Discovered["score"],
    score_model: "edge_quality_v1",
    score_breakdown: { dp_strength: 24.0, sweeps: 15.0 },
    dp_direction: "ACCUMULATION",
    dp_strength: "80.0" as unknown as Discovered["dp_strength"],
    dp_sustained_days: 2,
    confluence: true,
    vol_oi: "2.4" as unknown as Discovered["vol_oi"],
    sweeps: 2,
    alert_count: 4,
    spot: "5.20" as unknown as Discovered["spot"],
    dp_status: "ok",
    sector: "Technology",
    scored_at: new Date(NOW_MS).toISOString(),
    latest_alert_at: new Date(NOW_MS - 15 * 60_000).toISOString(),
    ...overrides,
  };
}

describe("DiscoveredCard", () => {
  it("renders the edge-quality score and 5-factor breakdown", () => {
    render(<DiscoveredCard candidate={makeDiscovered()} nowMs={NOW_MS} />);
    expect(screen.getByText("ZAAA")).toBeTruthy();
    expect(screen.getByText("78.5")).toBeTruthy();
    expect(screen.getByText(/ACC/)).toBeTruthy(); // DP direction badge
    expect(screen.getByText(/80/)).toBeTruthy(); // DP strength
    expect(screen.getByText(/2d/)).toBeTruthy(); // sustained days
    expect(screen.getByText(/✓/)).toBeTruthy(); // confluence
    expect(screen.getByText("DISCOVERED")).toBeTruthy();
  });

  it("uses bias-tinted color on the ticker", () => {
    render(<DiscoveredCard candidate={makeDiscovered()} nowMs={NOW_MS} />);
    const ticker = screen.getByText("ZAAA");
    expect((ticker as HTMLElement).style.color).toContain("--positive");
  });

  it("shows DP N/A when dp_status is degraded", () => {
    render(
      <DiscoveredCard
        candidate={makeDiscovered({
          dp_status: "degraded",
          dp_direction: "NO_DATA",
        })}
        nowMs={NOW_MS}
      />,
    );
    expect(screen.getByText(/DP N\/A/i)).toBeTruthy();
  });

  it("shows alert count and last-seen in the footer", () => {
    render(<DiscoveredCard candidate={makeDiscovered()} nowMs={NOW_MS} />);
    expect(screen.getByText(/4 alerts · last 15m ago/)).toBeTruthy();
  });

  it("explains the badge via title attribute", () => {
    render(<DiscoveredCard candidate={makeDiscovered()} nowMs={NOW_MS} />);
    const badge = screen.getByText("DISCOVERED");
    expect(badge.getAttribute("title")).toMatch(/market-wide flow-alerts/i);
  });

  it("+ Watchlist button calls addTicker then rescan with the ticker's sector", async () => {
    vi.mocked(api.addTicker).mockResolvedValue({ ok: true, ticker: "ZAAA" });
    vi.mocked(api.rescan).mockResolvedValue({
      job_id: "j1",
      status: "queued",
    } as unknown as Awaited<ReturnType<typeof api.rescan>>);

    render(<DiscoveredCard candidate={makeDiscovered()} nowMs={NOW_MS} />);
    fireEvent.click(screen.getByRole("button", { name: /Add ZAAA/i }));

    await waitFor(() => {
      expect(api.addTicker).toHaveBeenCalledWith({
        ticker: "ZAAA",
        sector: "Technology",
        notes: expect.stringMatching(/discovery/i),
      });
      expect(api.rescan).toHaveBeenCalledWith("ZAAA");
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
        nowMs={NOW_MS}
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

    render(<DiscoveredCard candidate={makeDiscovered()} nowMs={NOW_MS} />);
    fireEvent.click(screen.getByRole("button", { name: /Add ZAAA/i }));

    expect(await screen.findByText("✗ failed")).toBeTruthy();
    expect(api.rescan).not.toHaveBeenCalled();
  });
});
