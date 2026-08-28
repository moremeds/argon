import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DomainStateTab } from "@/components/macro/DomainStateTab";
import type { MacroDomainSlot } from "@/components/macro/types";
import FIXTURE from "../fixtures/macroDomainStates.json";

/**
 * Tabs 03 (inflation) and 04 (USD) as a rendered thing.
 *
 * The fixture is the same frozen production `/api/macro/*` payload `macroDesk.test.tsx`
 * uses — real values, captured 2026-08-23. That is deliberate: these tabs are a
 * presentation merge of what `/macro` already renders, so if the two surfaces ever
 * disagree about the same response they will disagree here first.
 */
const D = FIXTURE.domains as unknown as Record<
  string,
  NonNullable<MacroDomainSlot["value"]>
>;

describe("DomainStateTab", () => {
  it("renders the same card the desk renders, for the domain it was given", () => {
    render(<DomainStateTab domain="inflation" slot={{ value: D.inflation }} />);
    const card = screen.getByTestId("macro-domain-inflation");
    expect(within(card).getByText("WELL_ABOVE_TARGET")).toBeTruthy();
    // The heading names the domain, so a tab reached by URL is identifiable without the
    // tab bar above it.
    expect(
      screen.getByRole("heading", { name: "Inflation", level: 1 }),
    ).toBeTruthy();
  });

  it("keeps the empty slot three-state", () => {
    // §9 invariant 2. `_domain_state` 404s rather than recomputing, and `allow404` turns
    // that into a null VALUE — a fact about the pipeline. An unreachable API is a
    // different fact and must not read as the same one.
    const never = render(
      <DomainStateTab domain="usd" slot={{ value: null }} />,
    );
    expect(
      within(never.getByTestId("macro-domain-usd")).getByText(
        /engine has not run/i,
      ),
    ).toBeTruthy();
    never.unmount();

    const failed = render(
      <DomainStateTab
        domain="usd"
        slot={{ value: null, error: "The usd state API request failed: boom" }}
      />,
    );
    const card = failed.getByTestId("macro-domain-usd");
    expect(within(card).getByText(/request failed: boom/)).toBeTruthy();
    expect(within(card).queryByText(/engine has not run/i)).toBeNull();
  });

  it("states what it refuses, and carries no composite in its own chrome", () => {
    render(<DomainStateTab domain="usd" slot={{ value: D.usd }} />);
    const refuses = screen.getByTestId("macro-domain-refuses-usd");
    // §1 / §9 invariant 1: the tab may not imply the four domains can be averaged, and
    // the chain-level claim has exactly one home.
    expect(refuses.textContent).toMatch(/does not combine this domain/i);
    expect(refuses.textContent).toMatch(/reading order, not a causal one/i);
    expect(refuses.textContent).toMatch(/no score, allocation or probability/i);
  });

  it("never prescribes", () => {
    // §9 invariant 7, asserted at runtime the way `gold-page.spec.ts` does — the
    // build-time posture lint covers the source, this covers what actually renders.
    render(<DomainStateTab domain="inflation" slot={{ value: D.inflation }} />);
    const body =
      screen.getByTestId("macro-domain-tab-inflation").textContent ?? "";
    expect(body.toLowerCase()).not.toMatch(/\bbuy\b|\bsell\b/);
    expect(body.toLowerCase()).not.toMatch(/position size|predicted return/);
  });
});
