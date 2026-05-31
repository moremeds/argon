/* @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { FrameworkTab } from "@/components/stock/tabs/FrameworkTab";
import type { components } from "@/lib/types";

type Framework = components["schemas"]["TradeFramework"];

const hookReturn = {
  latestForTicker: {
    codex: null as unknown,
    claude: null as unknown,
    deepseek: null as unknown,
  },
  pendingIdsForTicker: { codex: null, claude: null, deepseek: null },
  run: vi.fn(),
  canRun: true,
  actionLabel: "Run Analysis",
  unavailableForTicker: false,
};

vi.mock(
  "@/components/stock/panels/tradeInsightsAi/useAiAnalysisPolling",
  () => ({
    PROVIDERS: ["codex", "claude", "deepseek"] as const,
    useAiAnalysisPolling: () => hookReturn,
  }),
);

function framework(overrides: Partial<Framework> = {}): Framework {
  return {
    header: {
      thesis_one_liner: "Constructive swing setup",
      position_type: "swing",
      spot: "100",
      conviction_n: 5,
    },
    three_axis: {
      direction: { verdict: "bull", prose: "above flip, higher highs" },
      vega: {
        regime: "low_iv",
        ivr: "20",
        term_slope: "contango",
        prose: "cheap vol",
      },
      asymmetry: {
        rule_on: true,
        structure_family: "directional_defined_risk",
        prose: "defined-risk debit spread",
      },
    },
    gamma: {
      regime: "long",
      flip_strike: "98",
      call_wall: "110",
      put_wall: "90",
      prose: "dealers long gamma above flip",
    },
    catalyst: {
      next_er_date: null,
      dte_to_er: null,
      implied_move: null,
      handling: "stand_aside",
      prose: "no near catalyst",
    },
    conviction: {
      score: 5,
      factors: [
        { name: "Trend alignment", status: "yes", note: "all up" },
        { name: "Earnings reaction history", status: "na", note: "" },
        { name: "Flow footprint", status: "yes", note: "" },
        { name: "Vol regime", status: "yes", note: "" },
        { name: "Liquidity / OI", status: "no", note: "" },
        { name: "Gamma posture", status: "yes", note: "" },
        { name: "Catalyst timing", status: "na", note: "" },
        { name: "Confluence", status: "yes", note: "" },
      ],
      prose: "5 of 8 confirmed",
    },
    confluence: {
      aligned: true,
      signals: [
        { name: "flow", direction: "bull" },
        { name: "gamma", direction: "bull" },
      ],
      prose: "",
    },
    pitfalls: [
      { id: "p01", title: "Chasing extension", triggered: false, note: "" },
    ],
    candidates: [
      {
        name: "bull_call_spread",
        legs: ["+1 100C", "-1 110C"],
        debit_credit: "debit",
        net_delta: "0.35",
        net_vega: "-0.02",
        pnl_bull: "+380",
        pnl_base: "+120",
        pnl_bear: "-320",
        defined_risk: true,
      },
    ],
    best_setup: {
      structure: "bull_call_spread",
      legs: ["+1 100C", "-1 110C"],
      cost: "$3.20 debit",
      max_risk: "capped -$320",
      rationale: "Lean long into strength with defined risk.",
      why_not_alternatives: "naked calls = undefined vega risk",
      invalidation: "daily close < 97",
    },
    what_changes: [{ signal: "loss of the flip", effect: "flip to neutral" }],
    bottom_line: "Lean long into strength.",
    ...overrides,
  };
}

function succeeded(
  fw: Framework | null,
  opts: { entryState?: string; missingData?: string[] } = {},
) {
  return {
    status: "succeeded",
    outcome: fw
      ? {
          framework: fw,
          headline: { entry_state: opts.entryState ?? "ACTIVE" },
          missing_data: opts.missingData ?? [],
        }
      : {},
    error_message: null,
  };
}

describe("FrameworkTab", () => {
  beforeEach(() => {
    hookReturn.latestForTicker = {
      codex: succeeded(framework()),
      claude: { status: "failed", outcome: null, error_message: "boom" },
      deepseek: null,
    };
    hookReturn.pendingIdsForTicker = {
      codex: null,
      claude: null,
      deepseek: null,
    };
  });

  it("renders a 3-provider toggle with state badges", () => {
    render(<FrameworkTab ticker="NVDA" />);
    expect(screen.getByText("Codex")).toBeTruthy();
    expect(screen.getByText("Claude")).toBeTruthy();
    expect(screen.getByText("DeepSeek")).toBeTruthy();
    expect(screen.getByText("ready")).toBeTruthy();
    expect(screen.getByText("failed")).toBeTruthy();
    expect(screen.getByText("not run")).toBeTruthy();
  });

  it("renders the active provider's decision stack ending in best_setup", () => {
    render(<FrameworkTab ticker="NVDA" />);
    expect(screen.getByText("Best Setup")).toBeTruthy();
    // structure appears both in the candidate ladder and the best-setup card
    expect(screen.getAllByText("bull_call_spread").length).toBeGreaterThan(0);
    expect(screen.getByText("Lean long into strength.")).toBeTruthy();
  });

  it("shows na factor status as 'na' not blank", () => {
    render(<FrameworkTab ticker="NVDA" />);
    // two conviction factors have status na
    expect(screen.getAllByText("na").length).toBeGreaterThan(0);
  });

  it("shows single-provider consensus banner when <2 frameworks", () => {
    render(<FrameworkTab ticker="NVDA" />);
    expect(screen.getByText(/single provider/i)).toBeTruthy();
  });

  it("shows cross-model consensus when >=2 frameworks agree", () => {
    hookReturn.latestForTicker = {
      codex: succeeded(framework()),
      claude: succeeded(framework()),
      deepseek: null,
    };
    render(<FrameworkTab ticker="NVDA" />);
    expect(screen.getByText(/consensus: swing/i)).toBeTruthy();
  });

  // v2 spec §5.6 MUST-1: no_conflict renders visibly differently from stand_aside.
  it("renders no_conflict catalyst with the friendly label", () => {
    const fw = framework({
      catalyst: {
        next_er_date: null,
        dte_to_er: null,
        implied_move: null,
        handling: "no_conflict",
        prose: "53 DTE — no event risk in trade horizon",
      },
    });
    hookReturn.latestForTicker = {
      codex: succeeded(fw),
      claude: null,
      deepseek: null,
    };
    render(<FrameworkTab ticker="NVDA" />);
    // friendly label, not the raw enum string
    expect(screen.getByText("no event risk")).toBeTruthy();
  });

  // v2 spec §5.6 MUST-2: auto-correct: missing_data items surface adjacent
  // to entry_state, NOT buried in the generic missing-data list.
  it("surfaces an auto-correct note adjacent to entry_state", () => {
    const fw = framework();
    hookReturn.latestForTicker = {
      codex: succeeded(fw, {
        entryState: "CONDITIONAL",
        missingData: [
          "auto-correct: headline.entry_state: 'ACTIVE' -> 'CONDITIONAL' (thesis_fired=True, entry_fired=False, invalidation_fired=False). v5.3 ENTRY_STATE is mechanical when the truth table is unambiguous.",
        ],
      }),
      claude: null,
      deepseek: null,
    };
    render(<FrameworkTab ticker="NVDA" />);
    // The strip label + the correction badge both render.
    expect(screen.getByText("Entry state")).toBeTruthy();
    expect(screen.getByText("State corrected")).toBeTruthy();
    expect(screen.getByTestId("entry-state-autocorrect")).toBeTruthy();
  });

  it("hides auto-correct affordance when no correction fired", () => {
    const fw = framework();
    hookReturn.latestForTicker = {
      codex: succeeded(fw, { entryState: "ACTIVE", missingData: [] }),
      claude: null,
      deepseek: null,
    };
    render(<FrameworkTab ticker="NVDA" />);
    expect(screen.queryByText("State corrected")).toBeNull();
    expect(screen.queryByTestId("entry-state-autocorrect")).toBeNull();
  });
});
