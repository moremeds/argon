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

// --- The chain-level refusal -------------------------------------------------
//
// Four individually-fresh cards cannot show that USD stood on last night's rates: every
// row they fetch is current and honest. Only the snapshot carries the claim that the four
// belong together, so the desk renders its verdict WITHOUT hiding the cards -- an operator
// still needs to see what each engine said while being told not to read them as a chain.

type Snapshot = NonNullable<Parameters<typeof MacroDesk>[0]["snapshot"]>;

function snapshot(over: Partial<Snapshot> = {}): Snapshot {
  return {
    requested_as_of: "2026-08-24T07:40:00Z",
    as_of: "2026-08-24T07:40:00Z",
    assembled_at: "2026-08-24T07:41:00Z",
    status: "complete",
    assembler_version: "snapshot/1",
    inputs_hash: "f".repeat(64),
    domains: [
      { domain: "inflation", ordinal: 0, state_id: 1, state: "ABOVE_TARGET", direction: "FALLING", confidence: "0.71", as_of: "2026-08-24T07:40:00Z", engine_version: "inflation/2", inputs_hash: "a".repeat(64) },
      { domain: "policy_rates", ordinal: 1, state_id: 2, state: "ON_HOLD", direction: "FLAT", confidence: "0.66", as_of: "2026-08-24T07:40:00Z", engine_version: "rates/2", inputs_hash: "b".repeat(64) },
      { domain: "usd", ordinal: 2, state_id: 3, state: "RANGEBOUND", direction: "FLAT", confidence: "0.58", as_of: "2026-08-24T07:40:00Z", engine_version: "usd/3", inputs_hash: "c".repeat(64) },
      { domain: "gold", ordinal: 3, state_id: 4, state: "OPERATIVE", direction: "FLAT", confidence: "0.44", as_of: "2026-08-24T07:40:00Z", engine_version: "gold/2", inputs_hash: "d".repeat(64) },
    ],
    reasons: [],
    ...over,
  } as Snapshot;
}

describe("MacroDesk chain coherence", () => {
  it("says nothing when the chain is coherent", () => {
    render(<MacroDesk domains={slots()} snapshot={snapshot()} />);
    expect(screen.queryByTestId("macro-chain-refusal")).toBeNull();
  });

  it("names an absent domain without hiding the three that answered", () => {
    render(
      <MacroDesk
        domains={slots()}
        snapshot={snapshot({
          status: "partial",
          domains: (snapshot().domains ?? []).filter((d) => d.domain !== "policy_rates"),
          reasons: [
            { domain: "policy_rates", kind: "absent", detail: "no policy_rates state at or before this instant" },
          ],
        })}
      />,
    );
    const banner = screen.getByTestId("macro-chain-refusal");
    expect(banner.textContent).toMatch(/policy_rates/);
    // Option A: the cards stay. Reporting is the authority here, not withholding.
    expect(screen.getAllByTestId(/^macro-domain-/)).toHaveLength(4);
    expect(
      within(screen.getByTestId("macro-domain-usd")).getByText("RANGEBOUND"),
    ).toBeTruthy();
  });

  it("distinguishes a broken chain from a merely incomplete one", () => {
    render(
      <MacroDesk
        domains={slots()}
        snapshot={snapshot({
          status: "incompatible",
          reasons: [
            { domain: "usd", kind: "incompatible", detail: "usd cited policy_rates state 41, the snapshot holds 47" },
          ],
        })}
      />,
    );
    const banner = screen.getByTestId("macro-chain-refusal");
    expect(banner.getAttribute("data-status")).toBe("incompatible");
    expect(within(banner).getByText(/cited policy_rates state 41/)).toBeTruthy();
  });

  it("marks the offending card, so the banner is not the only place to look", () => {
    render(
      <MacroDesk
        domains={slots()}
        snapshot={snapshot({
          status: "incompatible",
          reasons: [
            { domain: "usd", kind: "incompatible", detail: "usd cited a superseded policy_rates state" },
          ],
        })}
      />,
    );
    expect(screen.getByTestId("macro-chain-flag-usd")).toBeTruthy();
    expect(screen.queryByTestId("macro-chain-flag-gold")).toBeNull();
  });

  it("says a snapshot was never assembled rather than implying coherence", () => {
    render(<MacroDesk domains={slots()} snapshot={null} />);
    const note = screen.getByTestId("macro-chain-unassembled");
    expect(note.textContent).toMatch(/never/i);
    // Absence of a snapshot must never read as a clean chain.
    expect(screen.queryByTestId("macro-chain-refusal")).toBeNull();
  });

  // Scoped to the BANNER, not the whole render -- the same trap the desk-chrome test
  // above documents. Gold's own note says the valuation lens "never becomes a price
  // target, an allocation, or a size", and a container-wide /allocat/i would flag that
  // disclaimer as if it were the recommendation it exists to refuse.
  it("reports the breakage without telling anyone what to do about it", () => {
    render(
      <MacroDesk
        domains={slots()}
        snapshot={snapshot({
          status: "incompatible",
          reasons: [{ domain: "usd", kind: "incompatible", detail: "usd cited a superseded policy_rates state" }],
        })}
      />,
    );
    const text = screen.getByTestId("macro-chain-refusal").textContent ?? "";
    for (const banned of [/reduce/i, /hedge/i, /position/i, /allocat/i, /recommend/i, /you should/i]) {
      expect(text).not.toMatch(banned);
    }
  });
});
