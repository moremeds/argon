/* @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CandidateCard } from "@/components/scanner/CandidateCard";
import { SignalRow } from "@/components/scanner/SignalRow";
import type { components } from "@/lib/types";

type Candidate = components["schemas"]["ScannerCandidate"];

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
        evidence: { direction: "short", total_premium: "1500000", top_dte: 30 },
        freshness: "live",
      },
    ],
    context_flags: [],
    gates: { earnings: "pass", liquidity: "pass", regime: "pass" },
    bias: "bearish",
    bias_strength: "moderate",
    setup: "ready",
    setup_reason: null,
    scanned_at: new Date().toISOString(),
    ...overrides,
  };
}

describe("CandidateCard", () => {
  it("renders ticker, spot, score, and Evaluate link", () => {
    render(<CandidateCard candidate={makeCandidate()} />);

    expect(screen.getByText("AAPL")).toBeTruthy();
    expect(screen.getByText("$185.20")).toBeTruthy();
    expect(screen.getByText("8.10")).toBeTruthy();
    expect(screen.getByText("Evaluate →")).toBeTruthy();
  });

  it("shows the multi-signal star only when is_type_f is true", () => {
    const { rerender } = render(<CandidateCard candidate={makeCandidate()} />);

    expect(screen.queryByText("*")).toBeNull();

    rerender(<CandidateCard candidate={makeCandidate({ is_type_f: true })} />);

    expect(screen.getByText("*")).toBeTruthy();
  });

  it("renders bias arrow + strength for bearish (no bias word in card)", () => {
    render(<CandidateCard candidate={makeCandidate()} />);

    expect(screen.getByText("▼")).toBeTruthy();
    expect(screen.getByText("moderate")).toBeTruthy();
  });

  it("renders up arrow for bullish bias", () => {
    render(
      <CandidateCard
        candidate={makeCandidate({ bias: "bullish", bias_strength: "strong" })}
      />,
    );

    expect(screen.getByText("▲")).toBeTruthy();
    expect(screen.getByText("strong")).toBeTruthy();
  });

  it("omits the bias indicator entirely when bias is neutral", () => {
    render(
      <CandidateCard
        candidate={makeCandidate({ bias: "neutral", bias_strength: null })}
      />,
    );

    expect(screen.queryByText("▲")).toBeNull();
    expect(screen.queryByText("▼")).toBeNull();
    expect(screen.queryByText("◆")).toBeNull();
  });

  it("tints the ticker color to match bias", () => {
    render(<CandidateCard candidate={makeCandidate()} />);

    const ticker = screen.getByText("AAPL");
    expect((ticker as HTMLElement).style.color).toContain("--negative");
  });

  it("renders READY pill when all gates pass", () => {
    render(<CandidateCard candidate={makeCandidate()} />);

    expect(screen.getByText("READY")).toBeTruthy();
  });

  it("adds an explanatory title to the setup pill so the gate meaning is discoverable", () => {
    render(<CandidateCard candidate={makeCandidate()} />);

    // The pill wraps the READY label — walk up one level to get the title-bearing span.
    const pill = screen.getByText("READY").parentElement as HTMLElement | null;
    expect(pill).not.toBeNull();
    expect(pill?.getAttribute("title")).toMatch(/risk gates pass/i);
    expect(pill?.getAttribute("title")).toMatch(/not a buy signal/i);
  });

  it("renders CAUTION pill with reason when a gate blocks", () => {
    render(
      <CandidateCard
        candidate={makeCandidate({
          gates: { earnings: "block", liquidity: "pass", regime: "pass" },
          setup: "caution",
          setup_reason: "earnings",
        })}
      />,
    );

    expect(screen.getByText("CAUTION")).toBeTruthy();
    expect(screen.getByText(/earnings/)).toBeTruthy();
  });

  it("colors the final score by setup state", () => {
    render(<CandidateCard candidate={makeCandidate({ setup: "caution" })} />);

    const score = screen.getByText("8.10");
    expect((score as HTMLElement).style.color).toContain("--warning");
  });

  it("does NOT render the legacy gates row", () => {
    render(<CandidateCard candidate={makeCandidate()} />);

    expect(screen.queryByText(/earnings\s*✓/i)).toBeNull();
    expect(screen.queryByText(/regime\s*✓/i)).toBeNull();
  });
});

describe("SignalRow", () => {
  it("renders Conviction Flow with direction, premium, DTE fallback, and primary tier label", () => {
    const candidate = makeCandidate();

    render(<SignalRow hit={candidate.hits[0]} />);

    expect(screen.getByText(/Conviction Flow/i)).toBeTruthy();
    expect(screen.getByText("primary")).toBeTruthy();
    expect(screen.getByText(/short/)).toBeTruthy();
    expect(screen.getByText(/1\.5M/)).toBeTruthy();
    // Falls back to DTE when no expiry is present on the hit.
    expect(screen.getByText(/30 DTE/)).toBeTruthy();
  });

  it("renders Conviction Flow with alert count, contract, expiry, and ask-side aggression", () => {
    const hit: Candidate["hits"][number] = {
      signal_type: "deep_conviction_flow",
      tier: 1,
      score: "0.85" as unknown as Candidate["hits"][number]["score"],
      evidence: {
        direction: "long",
        total_premium: "996000",
        qualifying_alerts: 7,
        top_strike: "270",
        top_option_type: "call",
        top_expiry: "2027-12-19",
        top_dte: 578,
        top_ask_side_ratio: "0.94",
      },
      freshness: "live",
    };

    render(<SignalRow hit={hit} />);

    expect(screen.getByText(/long/)).toBeTruthy();
    expect(screen.getByText(/996K/)).toBeTruthy();
    expect(screen.getByText(/7 alerts/)).toBeTruthy();
    expect(screen.getByText(/C 270/)).toBeTruthy();
    expect(screen.getByText(/12\/19\/27/)).toBeTruthy();
    expect(screen.getByText(/94% ask/)).toBeTruthy();
    // When the explicit expiry is present, DTE should not also render.
    expect(screen.queryByText(/578 DTE/)).toBeNull();
  });

  it("renders put contracts with a P prefix", () => {
    const hit: Candidate["hits"][number] = {
      signal_type: "deep_conviction_flow",
      tier: 1,
      score: "0.85" as unknown as Candidate["hits"][number]["score"],
      evidence: {
        direction: "short",
        total_premium: "1000000",
        top_strike: "150",
        top_option_type: "put",
        top_expiry: "2026-06-19",
      },
      freshness: "live",
    };

    render(<SignalRow hit={hit} />);

    expect(screen.getByText(/P 150/)).toBeTruthy();
  });

  it("omits unknown Conviction Flow direction", () => {
    const hit = {
      ...makeCandidate().hits[0],
      evidence: {
        direction: "unknown",
        total_premium: "1500000",
        top_dte: 30,
      },
    };

    render(<SignalRow hit={hit} />);

    expect(screen.queryByText(/unknown/)).toBeNull();
    expect(screen.getByText(/1\.5M/)).toBeTruthy();
  });

  it("renders Dark Pool with prints, notional, price range, vs-spot, and confirming tier label", () => {
    const hit: Candidate["hits"][number] = {
      signal_type: "dark_pool_accumulation",
      tier: 2,
      score: "0.50" as unknown as Candidate["hits"][number]["score"],
      evidence: {
        cluster_size: 492,
        total_premium: "147800000",
        anchor_price: "300.23",
        cluster_price_min: "299.80",
        cluster_price_max: "300.85",
        cluster_price_vwap: "300.20",
        vs_spot: "above",
        vs_spot_pct: "0.13",
        spot: "299.85",
      },
      freshness: "stale",
    };

    render(<SignalRow hit={hit} />);

    expect(screen.getByText(/Dark Pool/i)).toBeTruthy();
    expect(screen.getByText("confirming")).toBeTruthy();
    expect(screen.getByText(/492 prints/)).toBeTruthy();
    expect(screen.getByText(/147\.8M/)).toBeTruthy();
    expect(screen.getByText(/\$299\.80–\$300\.85/)).toBeTruthy();
    expect(screen.getByText(/0\.13% above/)).toBeTruthy();
  });

  it("falls back to vwap when min and max are identical", () => {
    const hit: Candidate["hits"][number] = {
      signal_type: "dark_pool_accumulation",
      tier: 2,
      score: "0.50" as unknown as Candidate["hits"][number]["score"],
      evidence: {
        cluster_size: 100,
        total_premium: "5000000",
        cluster_price_min: "190.00",
        cluster_price_max: "190.00",
        cluster_price_vwap: "190.00",
        vs_spot: "at",
        vs_spot_pct: "0.00",
        spot: "190.00",
      },
      freshness: "stale",
    };

    render(<SignalRow hit={hit} />);

    expect(screen.getByText(/~\$190\.00/)).toBeTruthy();
    expect(screen.getByText(/at spot/)).toBeTruthy();
  });

  it("formats Dark Pool notional in billions when over $1B", () => {
    const hit: Candidate["hits"][number] = {
      signal_type: "dark_pool_accumulation",
      tier: 2,
      score: "1.00" as unknown as Candidate["hits"][number]["score"],
      evidence: {
        cluster_size: 492,
        total_premium: "12535000000",
        cluster_price_min: "299.80",
        cluster_price_max: "300.85",
        cluster_price_vwap: "300.20",
        vs_spot: "above",
        vs_spot_pct: "0.13",
        spot: "299.85",
      },
      freshness: "stale",
    };

    render(<SignalRow hit={hit} />);

    expect(screen.getByText(/12\.54B/)).toBeTruthy();
  });

  it("omits vs-spot piece when classification is unknown", () => {
    const hit: Candidate["hits"][number] = {
      signal_type: "dark_pool_accumulation",
      tier: 2,
      score: "0.50" as unknown as Candidate["hits"][number]["score"],
      evidence: {
        cluster_size: 100,
        total_premium: "5000000",
        anchor_price: "190.00",
        vs_spot: "unknown",
        vs_spot_pct: null,
        spot: null,
      },
      freshness: "stale",
    };

    render(<SignalRow hit={hit} />);

    expect(screen.queryByText(/spot/)).toBeNull();
  });
});
