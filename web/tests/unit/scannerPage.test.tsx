/* @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CandidateTile } from "@/components/scanner/CandidateTile";
import { GatedList } from "@/components/scanner/GatedList";
import { SignalBadge } from "@/components/scanner/SignalBadge";
import type { components } from "@/lib/types";

type Candidate = components["schemas"]["ScannerCandidate"];
type Gated = components["schemas"]["ScannerGatedTicker"];

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn() }),
}));

vi.mock("@/lib/api", () => ({
  api: {
    job: vi.fn(),
    rescan: vi.fn(),
  },
}));

afterEach(() => {
  vi.clearAllMocks();
});

function makeCandidate(overrides: Partial<Candidate> = {}): Candidate {
  return {
    ticker: "AAPL",
    spot: "185.20" as unknown as Candidate["spot"],
    is_type_f: false,
    raw_score: "5.10" as unknown as Candidate["raw_score"],
    confluence_score: "3.0" as unknown as Candidate["confluence_score"],
    final_score: "8.10" as unknown as Candidate["final_score"],
    hits: [
      {
        signal_type: "deep_conviction_flow",
        tier: 1,
        score: "0.85" as unknown as Candidate["hits"][number]["score"],
        evidence: { total_premium: "1500000", top_dte: 30 },
        freshness: "live",
      },
    ],
    context_flags: [],
    gates: { earnings: "pass", liquidity: "pass", regime: "pass" },
    scanned_at: new Date().toISOString(),
    ...overrides,
  };
}

describe("CandidateTile", () => {
  it("renders ticker, spot, score, and Evaluate link", () => {
    render(<CandidateTile candidate={makeCandidate()} />);

    expect(screen.getByText("AAPL")).toBeTruthy();
    expect(screen.getByText("$185.20")).toBeTruthy();
    expect(screen.getByText("8.10")).toBeTruthy();
    expect(screen.getByText("Evaluate →")).toBeTruthy();
  });

  it("shows the type-F marker only when is_type_f is true", () => {
    const { rerender } = render(<CandidateTile candidate={makeCandidate()} />);

    expect(screen.queryByText("*")).toBeNull();

    rerender(<CandidateTile candidate={makeCandidate({ is_type_f: true })} />);

    expect(screen.getByText("*")).toBeTruthy();
  });
});

describe("SignalBadge", () => {
  it("renders DCF with premium and DTE", () => {
    const candidate = makeCandidate();

    render(<SignalBadge hit={candidate.hits[0]} />);

    expect(screen.getByText(/DCF/)).toBeTruthy();
    expect(screen.getByText(/1\.5M/)).toBeTruthy();
    expect(screen.getByText(/30 DTE/)).toBeTruthy();
  });
});

describe("GatedList", () => {
  it("renders nothing when no gated tickers", () => {
    const { container } = render(<GatedList gated={[]} />);

    expect(container.firstChild).toBeNull();
  });

  it("shows blocking chip in the reason text", () => {
    const gated: Gated[] = [
      {
        ticker: "AMD",
        reason: "regime_block",
        blocking_chip: "SUSPENDED",
        scanned_at: new Date().toISOString(),
      },
    ];

    render(<GatedList gated={gated} />);

    expect(screen.getByText("AMD")).toBeTruthy();
    expect(
      screen.getByText(/regime block \(structural posture: SUSPENDED\)/),
    ).toBeTruthy();
  });
});
