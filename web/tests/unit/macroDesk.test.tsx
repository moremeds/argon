import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MacroDesk } from "@/components/macro/MacroDesk";
import type { MacroDomainSlot } from "@/components/macro/types";
import FIXTURE from "../fixtures/macroDomainStates.json";

// Real /api/macro/* responses frozen 2026-08-23. See the fixture's _note.
const D = FIXTURE.domains as unknown as Record<
  string,
  NonNullable<MacroDomainSlot["value"]>
>;

function slots(over: Partial<Record<string, MacroDomainSlot>> = {}) {
  return {
    inflation: { value: D.inflation, error: undefined },
    policy_rates: { value: D.rates, error: undefined },
    usd: { value: D.usd, error: undefined },
    gold: { value: D.gold, error: undefined },
    ...over,
  } as Record<string, MacroDomainSlot>;
}

describe("MacroDesk", () => {
  it("renders the four domains in causal order, not as four peers", () => {
    render(<MacroDesk domains={slots()} />);
    const cards = screen.getAllByTestId(/^macro-domain-/);
    expect(cards.map((c) => c.getAttribute("data-testid"))).toEqual([
      "macro-domain-inflation",
      "macro-domain-policy_rates",
      "macro-domain-usd",
      "macro-domain-gold",
    ]);
  });

  it("shows each domain's state and direction", () => {
    render(<MacroDesk domains={slots()} />);
    const usd = screen.getByTestId("macro-domain-usd");
    expect(within(usd).getByText("RANGEBOUND")).toBeTruthy();
    expect(within(usd).getByText(/FLAT/)).toBeTruthy();
  });

  it("names a domain that failed to load rather than blanking it", () => {
    render(
      <MacroDesk
        domains={slots({
          gold: { value: null, error: "The gold request failed: API 503" },
        })}
      />,
    );
    const gold = screen.getByTestId("macro-domain-gold");
    expect(within(gold).getByText(/API 503/)).toBeTruthy();
    // The other three are unaffected -- one dead publisher is not a dead page.
    expect(
      within(screen.getByTestId("macro-domain-usd")).getByText("RANGEBOUND"),
    ).toBeTruthy();
  });

  it("distinguishes a domain that has never been computed from one that errored", () => {
    render(<MacroDesk domains={slots({ gold: { value: null } })} />);
    const gold = screen.getByTestId("macro-domain-gold");
    expect(within(gold).getByText(/no state has been computed/i)).toBeTruthy();
  });

  it("surfaces contradictions instead of hiding them behind the state", () => {
    render(<MacroDesk domains={slots()} />);
    const inflation = screen.getByTestId("macro-domain-inflation");
    // The frozen inflation state carries 2 contradictions.
    expect(
      within(inflation).getByTestId("macro-contradictions"),
    ).toBeTruthy();
  });

  it("reports the evidence count so a conclusion is never shown bare", () => {
    render(<MacroDesk domains={slots()} />);
    const usd = screen.getByTestId("macro-domain-usd");
    expect(within(usd).getByTestId("macro-evidence-count").textContent).toMatch(
      /\d/,
    );
  });

  // The ban is on the DESK synthesizing a verdict of its own. It is deliberately not a
  // substring scan over the whole render: the gold engine's own note reads "the valuation
  // lens is a warning: it never becomes a price target, an allocation, or a size", and a
  // blunt /allocat/i match flags that disclaimer as if it were a recommendation.
  it("adds no master score of its own to the desk chrome", () => {
    const empty = Object.fromEntries(
      ["inflation", "policy_rates", "usd", "gold"].map((d) => [d, { value: null }]),
    ) as Record<string, MacroDomainSlot>;
    const { container } = render(<MacroDesk domains={empty} />);
    const text = container.textContent ?? "";
    for (const banned of [
      /master score/i,
      /composite/i,
      /overall score/i,
      /allocat/i,
      /target weight/i,
      /probability/i,
    ]) {
      expect(text).not.toMatch(banned);
    }
  });

  it("renders exactly one state per domain and no fifth aggregate", () => {
    render(<MacroDesk domains={slots()} />);
    expect(screen.getAllByTestId(/^macro-domain-/)).toHaveLength(4);
    expect(screen.queryByTestId(/score|composite|aggregate/i)).toBeNull();
  });

  it("shows the engine version, because two engines are two semantics", () => {
    render(<MacroDesk domains={slots()} />);
    const usd = screen.getByTestId("macro-domain-usd");
    expect(within(usd).getByText(/usd\/\d/)).toBeTruthy();
  });
});
