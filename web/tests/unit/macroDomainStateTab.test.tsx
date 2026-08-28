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
  it("wears the board's state pill, not the desk's summary card", () => {
    render(<DomainStateTab domain="inflation" slot={{ value: D.inflation }} />);
    const pill = screen.getByTestId("macro-domain-inflation");
    // The board's `.sec-title` compresses the state into one pill: label · direction ·
    // confidence. The card this replaced stays on /macro, the overview it was built for.
    expect(pill.className).toContain("state");
    expect(pill.textContent).toMatch(/WELL_ABOVE_TARGET · FLAT · conf 0\.\d\d/);
    // Coloured by distance from the domain's own target, never by a market view.
    expect(pill.className).toContain("warnst");
    // The heading names the domain, so a tab reached by URL is identifiable without the
    // tab bar above it.
    expect(
      screen.getByRole("heading", { name: "Inflation", level: 1 }),
    ).toBeTruthy();
  });

  it("derives the sub-title clause the card's rows used to carry", () => {
    // The board writes this as prose — "two contradiction rules are firing and one
    // expectations input is 60 days stale" — and every part is on the response. It is
    // computed, never copied: the board's own figures froze at its capture instant.
    render(<DomainStateTab domain="inflation" slot={{ value: D.inflation }} />);
    const sub = screen
      .getByTestId("macro-domain-tab-inflation")
      .querySelector(".sec-sub");
    const text = sub?.textContent ?? "";
    const rules = D.inflation.contradictions ?? [];
    expect(text).toContain(`${rules.length} contradiction rule`);
    for (const r of rules) expect(text).toContain(r.rule);
    // The stalest input is named, and it is the max over the published factors rather
    // than a series picked by hand.
    const oldest = (D.inflation.factors ?? []).reduce((a, b) =>
      b.age_days > a.age_days ? b : a,
    );
    expect(text).toContain(`${oldest.series_id} at ${oldest.age_days}d`);
  });

  it("advertises exactly the questions its panels answer", () => {
    // The tab-level strip is written down in `TAB_QUESTIONS` because the panels are
    // opaque children by the time the header renders. This is the check that keeps it
    // honest: recompute the union from the panels' own `data-questions` and compare.
    for (const [domain, value] of [
      ["inflation", D.inflation],
      ["usd", D.usd],
    ] as const) {
      const view = render(<DomainStateTab domain={domain} slot={{ value }} />);
      const root = view.getByTestId(`macro-domain-tab-${domain}`);
      const union = new Set<string>();
      for (const p of root.querySelectorAll("[data-questions]")) {
        for (const q of (p.getAttribute("data-questions") ?? "").split(/\s+/))
          if (q) union.add(q);
      }
      const advertised = new Set(
        (root.querySelector(".sec-title .tag.q")?.textContent ?? "").split(
          /\s+/,
        ),
      );
      expect([...advertised].sort()).toEqual([...union].sort());
      expect(union.size).toBeGreaterThan(0);
      view.unmount();
    }
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
