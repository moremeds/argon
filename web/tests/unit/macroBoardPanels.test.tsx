import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DomainStateTab } from "@/components/macro/DomainStateTab";
import {
  confidenceChain,
  repairTable,
} from "@/components/macro/domain/confidence";
import type {
  MacroDomainSlot,
  MacroDomainState,
} from "@/components/macro/types";
import FIXTURE from "../fixtures/macroDomainStates.json";

/**
 * The board's panels for tabs 03 and 04, against the same frozen production payload the
 * rest of the macro suite uses.
 *
 * These six panels replaced the original two generic summaries. The first assertion is
 * simply that they are there and carry their board question — the acceptance test the
 * initial port lost.
 */
const D = FIXTURE.domains as unknown as Record<string, MacroDomainState>;

function slotOf(domain: string): MacroDomainSlot {
  return { value: D[domain] };
}

describe("confidence arithmetic", () => {
  it("reproduces the engine's published confidence from its own terms", () => {
    // 1 x 0.5645... x 1.0 x (1-0) x (1-0.30) = 0.39516..., which is what the fixture's
    // `confidence` field says. If this ever fails the panel is required to SAY so rather
    // than print a tidy chain beside a number it does not produce.
    const chain = confidenceChain(
      D.inflation.confidence_reasons ?? [],
      D.inflation.confidence,
    );
    expect(chain.reconciles).toBe(true);
    expect(chain.product).toBeCloseTo(Number(D.inflation.confidence), 12);
  });

  it("keeps a term that did not fire", () => {
    // The board's own chain omits `revision_penalty` because it was 0 that day. Omitting
    // it makes "no input was revised" indistinguishable from "revisions are not checked".
    const chain = confidenceChain(
      D.inflation.confidence_reasons ?? [],
      D.inflation.confidence,
    );
    const revision = chain.terms.find((t) => t.term === "revision_penalty");
    expect(revision).toBeDefined();
    expect(revision?.factor).toBe(1);
  });

  it("refuses to reconcile when the terms and the number disagree", () => {
    const chain = confidenceChain(D.inflation.confidence_reasons ?? [], "0.99");
    expect(chain.reconciles).toBe(false);
  });

  it("never multiplies an informational term into the product", () => {
    // USD carries `upstream_policy_rates` at 0.850 as `informational`. Multiplying it
    // would silently import the upstream's confidence into this domain's own.
    const chain = confidenceChain(
      D.usd.confidence_reasons ?? [],
      D.usd.confidence,
    );
    expect(chain.informational.map((r) => r.term)).toContain(
      "upstream_policy_rates",
    );
    expect(chain.reconciles).toBe(true);
    expect(chain.product).toBe(1);
  });

  it("prices one repair at a time, and never invents an event probability", () => {
    const chain = confidenceChain(
      D.inflation.confidence_reasons ?? [],
      D.inflation.confidence,
    );
    const table = repairTable(chain);
    // Two terms are degrading it: freshness and the contradiction penalty.
    expect(table.rows.map((r) => r.term).sort()).toEqual([
      "contradiction_penalty",
      "freshness",
    ]);
    const freshness = table.rows.find((r) => r.term === "freshness");
    // Clearing freshness alone leaves the 0.30 contradiction penalty standing: 1 x 0.70.
    expect(freshness?.to).toBeCloseTo(0.7, 12);
    expect(table.allClear).toBe(1);
  });

  it("has nothing to repair when every term is already clear", () => {
    const table = repairTable(
      confidenceChain(D.usd.confidence_reasons ?? [], D.usd.confidence),
    );
    expect(table.rows).toHaveLength(0);
    expect(table.allClear).toBeNull();
  });
});

describe("board panels on tabs 03 and 04", () => {
  it("renders the board's four inflation panels", () => {
    render(
      <DomainStateTab
        domain="inflation"
        slot={slotOf("inflation")}
        citedRates={D.rates}
      />,
    );
    for (const id of [
      "confidence-arithmetic",
      "confidence-repair",
      "realized-inflation",
      "inflation-expectations",
    ]) {
      expect(screen.getByTestId(`board-panel-${id}`)).toBeTruthy();
    }
  });

  it("renders the board's two dollar panels", () => {
    render(<DomainStateTab domain="usd" slot={slotOf("usd")} />);
    expect(screen.getByTestId("board-panel-dollar-pair")).toBeTruthy();
    expect(screen.getByTestId("board-panel-upstream-citation")).toBeTruthy();
  });

  it("gives every panel at least one board question — the acceptance test", () => {
    // "The seven questions are the acceptance test: every panel must answer at least
    // one, or it gets deleted." The tuple type makes an untagged panel a compile error;
    // this asserts the tag actually reaches the DOM, where a reviewer can see it.
    const { container, unmount } = render(
      <DomainStateTab
        domain="inflation"
        slot={slotOf("inflation")}
        citedRates={D.rates}
      />,
    );
    const panels = [
      ...container.querySelectorAll("[data-testid^='board-panel-']"),
    ];
    expect(panels.length).toBe(4);
    for (const panel of panels) {
      expect(panel.getAttribute("data-questions")).toMatch(
        /^Q[1-7]( Q[1-7])*$/,
      );
    }
    unmount();
  });

  it("renders no board panel when the domain has no state", () => {
    // Six empty frames would drown out the card's three-state message about WHY it is
    // empty, which is the more important thing on the page at that moment.
    const { container } = render(
      <DomainStateTab domain="usd" slot={{ value: null }} />,
    );
    expect(
      container.querySelectorAll("[data-testid^='board-panel-']"),
    ).toHaveLength(0);
  });
});

describe("the dollar pair reads its own data", () => {
  it("says 'same direction' when both legs move together", () => {
    // The fixture has both legs positive (+0.197 nominal, +1.163 real). The board's own
    // prose says "nominal falling, real rising" because that held on its capture day;
    // restating it here would print a claim the data contradicts.
    render(<DomainStateTab domain="usd" slot={slotOf("usd")} />);
    const read = screen.getByTestId("dollar-pair-read");
    expect(read.textContent).toMatch(/same direction/i);
    expect(read.textContent).not.toMatch(/opposite directions/i);
  });

  it("says 'opposite directions' when they diverge", () => {
    const diverged: MacroDomainState = {
      ...D.usd,
      velocity: (D.usd.velocity ?? []).map((v) =>
        v.metric === "broad_dollar_change" ? { ...v, value: "-1.09" } : v,
      ),
    };
    render(<DomainStateTab domain="usd" slot={{ value: diverged }} />);
    expect(screen.getByTestId("dollar-pair-read").textContent).toMatch(
      /opposite directions/i,
    );
  });

  it("carries the engine's own rule for the pair verbatim", () => {
    render(<DomainStateTab domain="usd" slot={slotOf("usd")} />);
    const panel = screen.getByTestId("board-panel-dollar-pair");
    expect(panel.querySelector("details")?.textContent).toMatch(
      /never substituted for it/,
    );
    expect(panel.getAttribute("data-basis")).toBe("COMPUTED");
  });
});

describe("the expectations citation", () => {
  it("computes the survey-vs-market gap from the two published levels", () => {
    render(
      <DomainStateTab
        domain="inflation"
        slot={slotOf("inflation")}
        citedRates={D.rates}
      />,
    );
    const split = screen.getByTestId("expectations-split");
    // MICH 4.6 against T10YIE, both off the fixture.
    expect(split.textContent).toMatch(/2\.26pp/);
    expect(split.textContent).toMatch(/4\.60% versus 2\.34%/);
  });

  it("says which half is missing when the rates citation fails", () => {
    render(
      <DomainStateTab
        domain="inflation"
        slot={slotOf("inflation")}
        citedRates={null}
        citationError="The rates state API request failed: boom"
      />,
    );
    expect(
      screen.getByTestId("expectations-citation-error").textContent,
    ).toMatch(/failed: boom/);
    expect(screen.queryByTestId("expectations-split")).toBeNull();
  });

  it("never composites the survey and the market reading", () => {
    render(
      <DomainStateTab
        domain="inflation"
        slot={slotOf("inflation")}
        citedRates={D.rates}
      />,
    );
    const panel = screen.getByTestId("board-panel-inflation-expectations");
    expect(within(panel).getByText(/remain separate/)).toBeTruthy();
    expect(panel.getAttribute("data-basis")).toBe("COMPUTED");
  });
});
