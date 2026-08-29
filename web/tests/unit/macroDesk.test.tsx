import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { OverviewDesk } from "@/components/macro/OverviewDesk";
import type { ReplayVerdict } from "@/components/macro/replay";
import type {
  MacroContextSnapshot,
  MacroDomainKey,
  MacroDomainState,
  MacroOverviewSlot,
} from "@/components/macro/types";
import FIXTURE from "../fixtures/macroDomainStates.json";

/**
 * The macro desk's invariant home, re-pointed by P5 from `MacroDesk` to `OverviewDesk`.
 *
 * `MacroDesk.tsx` was the `/macro` page's shell, and `/macro` is now
 * `redirect("/macro/overview")`. Every assertion below that held against the four-card
 * page still holds — the cards, the chain flags and the chain verdict all moved into tab
 * 00 unchanged — so this file was EXTENDED, not replaced: the original nine desk tests and
 * six chain tests are here verbatim in substance, with tab 00's own invariants added
 * after them.
 */

// Real /api/macro/* responses frozen 2026-08-23. See the fixture's _note.
const D = FIXTURE.domains as unknown as Record<string, MacroDomainState>;

/** Live: nothing was asked for, so no publisher has an instant to have answered for. */
const LIVE: ReplayVerdict = { kind: "not_replaying" };

type DomainSlots = Record<MacroDomainKey, MacroOverviewSlot<MacroDomainState>>;

/** One domain publisher's slot. Not generic: `slot(null)` would infer `T = null`. */
function dom(
  value: MacroDomainState | null,
  over: Partial<MacroOverviewSlot<MacroDomainState>> = {},
): MacroOverviewSlot<MacroDomainState> {
  return { value, verdict: LIVE, ...over };
}

/** The chain publisher's slot. */
function snap(
  value: MacroContextSnapshot | null,
  over: Partial<MacroOverviewSlot<MacroContextSnapshot>> = {},
): MacroOverviewSlot<MacroContextSnapshot> {
  return { value, verdict: LIVE, ...over };
}

function slots(over: Partial<DomainSlots> = {}): DomainSlots {
  return {
    inflation: dom(D.inflation),
    policy_rates: dom(D.rates),
    usd: dom(D.usd),
    gold: dom(D.gold),
    ...over,
  };
}

/** All four domains absent — the shape the desk chrome is scanned against. */
function noDomains(): DomainSlots {
  return {
    inflation: dom(null),
    policy_rates: dom(null),
    usd: dom(null),
    gold: dom(null),
  };
}

const NO_SNAPSHOT = snap(null);

function snapshot(
  over: Partial<MacroContextSnapshot> = {},
): MacroContextSnapshot {
  return {
    requested_as_of: "2026-08-24T07:40:00Z",
    as_of: "2026-08-24T07:40:00Z",
    assembled_at: "2026-08-24T07:41:00Z",
    status: "complete",
    assembler_version: "snapshot/1",
    inputs_hash: "f".repeat(64),
    domains: [
      {
        domain: "inflation",
        ordinal: 0,
        state_id: 1,
        state: "ABOVE_TARGET",
        direction: "FALLING",
        confidence: "0.71",
        as_of: "2026-08-24T07:40:00Z",
        engine_version: "inflation/2",
        inputs_hash: "a".repeat(64),
      },
      {
        domain: "policy_rates",
        ordinal: 1,
        state_id: 2,
        state: "ON_HOLD",
        direction: "FLAT",
        confidence: "0.66",
        as_of: "2026-08-24T07:40:00Z",
        engine_version: "rates/2",
        inputs_hash: "b".repeat(64),
      },
      {
        domain: "usd",
        ordinal: 2,
        state_id: 3,
        state: "RANGEBOUND",
        direction: "FLAT",
        confidence: "0.58",
        as_of: "2026-08-24T07:40:00Z",
        engine_version: "usd/3",
        inputs_hash: "c".repeat(64),
      },
      {
        domain: "gold",
        ordinal: 3,
        state_id: 4,
        state: "OPERATIVE",
        direction: "FLAT",
        confidence: "0.44",
        as_of: "2026-08-24T07:40:00Z",
        engine_version: "gold/2",
        inputs_hash: "d".repeat(64),
      },
    ],
    reasons: [],
    ...over,
  } as MacroContextSnapshot;
}

describe("OverviewDesk — the four domain states", () => {
  it("renders the four domains in causal order, not as four peers", () => {
    render(<OverviewDesk domains={slots()} snapshot={NO_SNAPSHOT} />);
    const cards = screen.getAllByTestId(/^macro-domain-/);
    expect(cards.map((c) => c.getAttribute("data-testid"))).toEqual([
      "macro-domain-inflation",
      "macro-domain-policy_rates",
      "macro-domain-usd",
      "macro-domain-gold",
    ]);
  });

  it("shows each domain's state and direction", () => {
    render(<OverviewDesk domains={slots()} snapshot={NO_SNAPSHOT} />);
    const usd = screen.getByTestId("macro-domain-usd");
    expect(within(usd).getByText("RANGEBOUND")).toBeTruthy();
    expect(within(usd).getByText(/FLAT/)).toBeTruthy();
  });

  it("names a domain that failed to load rather than blanking it", () => {
    render(
      <OverviewDesk
        domains={slots({
          gold: dom(null, { error: "The gold request failed: API 503" }),
        })}
        snapshot={NO_SNAPSHOT}
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
    render(
      <OverviewDesk
        domains={slots({ gold: dom(null) })}
        snapshot={NO_SNAPSHOT}
      />,
    );
    const gold = screen.getByTestId("macro-domain-gold");
    expect(within(gold).getByText(/no state has been computed/i)).toBeTruthy();
  });

  it("surfaces contradictions instead of hiding them behind the state", () => {
    render(<OverviewDesk domains={slots()} snapshot={NO_SNAPSHOT} />);
    const inflation = screen.getByTestId("macro-domain-inflation");
    // The frozen inflation state carries 2 contradictions.
    expect(within(inflation).getByTestId("macro-contradictions")).toBeTruthy();
  });

  it("reports the evidence count so a conclusion is never shown bare", () => {
    render(<OverviewDesk domains={slots()} snapshot={NO_SNAPSHOT} />);
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
    const { container } = render(
      <OverviewDesk domains={noDomains()} snapshot={NO_SNAPSHOT} />,
    );
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
    render(<OverviewDesk domains={slots()} snapshot={NO_SNAPSHOT} />);
    expect(screen.getAllByTestId(/^macro-domain-/)).toHaveLength(4);
    expect(screen.queryByTestId(/score|composite|aggregate/i)).toBeNull();
  });

  it("shows the engine version, because two engines are two semantics", () => {
    render(<OverviewDesk domains={slots()} snapshot={NO_SNAPSHOT} />);
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

describe("OverviewDesk chain coherence", () => {
  it("says nothing is broken when the chain is coherent, and says why that is narrow", () => {
    render(<OverviewDesk domains={slots()} snapshot={snap(snapshot())} />);
    expect(screen.queryByTestId("macro-chain-refusal")).toBeNull();
    // ...but it does not render NOTHING. On a tab whose subject is the chain, an empty
    // panel is indistinguishable from one that failed to load.
    const coherent = screen.getByTestId("macro-chain-coherent");
    expect(coherent.textContent).toMatch(
      /not a claim that the macro picture is right/i,
    );
    expect(coherent.textContent).toMatch(/internally coherent/i);
  });

  it("names an absent domain without hiding the three that answered", () => {
    render(
      <OverviewDesk
        domains={slots()}
        snapshot={snap(
          snapshot({
            status: "partial",
            domains: (snapshot().domains ?? []).filter(
              (d) => d.domain !== "policy_rates",
            ),
            reasons: [
              {
                domain: "policy_rates",
                kind: "absent",
                detail: "no policy_rates state at or before this instant",
              },
            ],
          }),
        )}
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
      <OverviewDesk
        domains={slots()}
        snapshot={snap(
          snapshot({
            status: "incompatible",
            reasons: [
              {
                domain: "usd",
                kind: "incompatible",
                detail:
                  "usd cited policy_rates state 41, the snapshot holds 47",
              },
            ],
          }),
        )}
      />,
    );
    const banner = screen.getByTestId("macro-chain-refusal");
    expect(banner.getAttribute("data-status")).toBe("incompatible");
    expect(
      within(banner).getByText(/cited policy_rates state 41/),
    ).toBeTruthy();
  });

  it("marks the offending card, so the banner is not the only place to look", () => {
    render(
      <OverviewDesk
        domains={slots()}
        snapshot={snap(
          snapshot({
            status: "incompatible",
            reasons: [
              {
                domain: "usd",
                kind: "incompatible",
                detail: "usd cited a superseded policy_rates state",
              },
            ],
          }),
        )}
      />,
    );
    expect(screen.getByTestId("macro-chain-flag-usd")).toBeTruthy();
    expect(screen.queryByTestId("macro-chain-flag-gold")).toBeNull();
  });

  it("says a snapshot was never assembled rather than implying coherence", () => {
    render(<OverviewDesk domains={slots()} snapshot={NO_SNAPSHOT} />);
    const note = screen.getByTestId("macro-chain-unassembled");
    expect(note.textContent).toMatch(/never/i);
    // Absence of a snapshot must never read as a clean chain.
    expect(screen.queryByTestId("macro-chain-refusal")).toBeNull();
    expect(screen.queryByTestId("macro-chain-coherent")).toBeNull();
  });

  // NEW in P5. `api.macroContextSnapshot` lets a 404 through as `null` and the page this
  // replaced ALSO caught a thrown request failure and returned `null`, so a dead API
  // printed "chain never assembled" -- a claim about the assembler made on the evidence of
  // a broken network. §9 invariant 2 requires three states, and this is the third.
  it("keeps an unreachable chain apart from one that was never assembled", () => {
    render(
      <OverviewDesk
        domains={slots()}
        snapshot={snap(null, {
          error: "The macro context snapshot API request failed: API 503",
        })}
      />,
    );
    const note = screen.getByTestId("macro-chain-unreachable");
    expect(note.textContent).toMatch(/API 503/);
    expect(note.textContent).toMatch(/fact about our API/i);
    expect(screen.queryByTestId("macro-chain-unassembled")).toBeNull();
  });

  // Scoped to the BANNER, not the whole render -- the same trap the desk-chrome test
  // above documents. Gold's own note says the valuation lens "never becomes a price
  // target, an allocation, or a size", and a container-wide /allocat/i would flag that
  // disclaimer as if it were the recommendation it exists to refuse.
  it("reports the breakage without telling anyone what to do about it", () => {
    render(
      <OverviewDesk
        domains={slots()}
        snapshot={snap(
          snapshot({
            status: "incompatible",
            reasons: [
              {
                domain: "usd",
                kind: "incompatible",
                detail: "usd cited a superseded policy_rates state",
              },
            ],
          }),
        )}
      />,
    );
    const text = screen.getByTestId("macro-chain-refusal").textContent ?? "";
    for (const banned of [
      /reduce/i,
      /hedge/i,
      /position/i,
      /allocat/i,
      /recommend/i,
      /you should/i,
    ]) {
      expect(text).not.toMatch(banned);
    }
  });
});

// --- Tab 00's own scope bound -------------------------------------------------
//
// Plan §8: tab 00 is the one slice with no existing component, "which is exactly why it
// is the one that can quietly become new analytics." These are the assertions that make
// that sentence enforceable.

describe("OverviewDesk — the daily loop", () => {
  it("lists the four domains in the ENGINE's causal order, not the tab strip's", () => {
    render(<OverviewDesk domains={slots()} snapshot={NO_SNAPSHOT} />);
    const rows = screen.getAllByTestId(/^macro-loop-/);
    expect(rows.map((r) => r.getAttribute("data-testid"))).toEqual([
      "macro-loop-inflation",
      "macro-loop-policy_rates",
      "macro-loop-usd",
      "macro-loop-gold",
    ]);
  });

  it("adds no fifth row summarising the four", () => {
    render(<OverviewDesk domains={slots()} snapshot={NO_SNAPSHOT} />);
    expect(screen.getAllByTestId(/^macro-loop-/)).toHaveLength(4);
  });

  it("keeps the three states apart per row, including in the loop", () => {
    render(
      <OverviewDesk
        domains={slots({
          gold: dom(null, {
            error: "The gold state API request failed: ECONNREFUSED",
          }),
          usd: dom(null),
        })}
        snapshot={NO_SNAPSHOT}
      />,
    );
    expect(screen.getByTestId("macro-loop-gold").textContent).toMatch(
      /ECONNREFUSED/,
    );
    expect(screen.getByTestId("macro-loop-usd").textContent).toMatch(
      /engine has not run/i,
    );
  });
});

describe("OverviewDesk — the contradiction feed", () => {
  it("gathers every domain's contradictions and attributes each one", () => {
    render(<OverviewDesk domains={slots()} snapshot={NO_SNAPSHOT} />);
    const feed = screen.getByTestId("macro-overview-contradictions");
    // The frozen states carry 2 (inflation) + 1 (rates) + 0 (usd) + 1 (gold).
    expect(
      within(feed).getAllByTestId(/^macro-contradiction-row-/),
    ).toHaveLength(4);
    expect(
      within(feed).getAllByTestId("macro-contradiction-row-inflation"),
    ).toHaveLength(2);
  });

  it("carries its own denominator, so a quiet feed cannot be read as good news", () => {
    render(
      <OverviewDesk
        domains={slots({ usd: dom(null), gold: dom(null) })}
        snapshot={NO_SNAPSHOT}
      />,
    );
    // "3 contradictions" alone is unreadable: a feed that is quiet because nothing fired
    // and one that is quiet because two engines never ran look identical.
    expect(screen.getByTestId("macro-contradiction-count").textContent).toMatch(
      /of 4 domains that answered/i,
    );
    expect(
      screen.getByTestId("macro-contradiction-unasked").textContent,
    ).toMatch(/not because/i);
  });

  it("orders by the engine's causal order and re-ranks nothing", () => {
    // The engines publish a rule and a detail — no weight, no level, no severity. Any
    // ordering beyond the producer's own would be a judgement invented in the browser,
    // which is plan §8's "a composite wearing a list's clothes".
    render(<OverviewDesk domains={slots()} snapshot={NO_SNAPSHOT} />);
    const feed = screen.getByTestId("macro-overview-contradictions");
    const order = within(feed)
      .getAllByTestId(/^macro-contradiction-row-/)
      .map((n) => n.getAttribute("data-testid"));
    expect(order).toEqual([
      "macro-contradiction-row-inflation",
      "macro-contradiction-row-inflation",
      "macro-contradiction-row-policy_rates",
      "macro-contradiction-row-gold",
    ]);
  });

  it("says an empty feed means nothing was asked when nothing answered", () => {
    render(<OverviewDesk domains={noDomains()} snapshot={NO_SNAPSHOT} />);
    expect(
      screen.getByTestId("macro-overview-contradictions").textContent,
    ).toMatch(/nothing was asked, not that nothing fired/i);
  });
});

describe("OverviewDesk — transmission health", () => {
  it("gives every one of the five publishers a row, three-state", () => {
    render(
      <OverviewDesk
        domains={slots({
          gold: dom(null, {
            error: "The gold state API request failed: API 503",
          }),
          usd: dom(null),
        })}
        snapshot={snap(snapshot())}
      />,
    );
    for (const id of ["snapshot", "inflation", "policy_rates", "usd", "gold"]) {
      expect(screen.getByTestId(`macro-health-${id}`)).toBeTruthy();
    }
    expect(
      screen.getByTestId("macro-health-usd").getAttribute("data-answered"),
    ).toBe("never computed");
    expect(
      screen.getByTestId("macro-health-gold").getAttribute("data-answered"),
    ).toBe("request failed");
    expect(
      screen
        .getByTestId("macro-health-inflation")
        .getAttribute("data-answered"),
    ).toBe("yes");
  });

  it("prints the upstream answers a state cited, and checks them against nothing", () => {
    render(<OverviewDesk domains={slots()} snapshot={NO_SNAPSHOT} />);
    const edges = screen.getByTestId("macro-transmission-edges");
    // usd cites policy_rates; gold cites policy_rates, usd and inflation.
    expect(edges.textContent).toMatch(/USD Transmission/);
    expect(edges.textContent).toMatch(/Gold Gate/);
    // Whether a cited upstream is the one the chain holds is the assembler's verdict,
    // published by /api/macro/snapshot. Re-deciding it from the edges here would be a
    // second opinion computed in a browser.
    expect(edges.textContent).not.toMatch(/incompatible|superseded|mismatch/i);
  });

  it("shows the two clocks as two columns", () => {
    // `as_of` is what the replay request bounds; `computed_at` is provenance and may
    // legitimately be much later (storage/macro_domain_state.py:216-219). One column
    // carrying both would let the second be read as the first.
    render(<OverviewDesk domains={slots()} snapshot={NO_SNAPSHOT} />);
    const panel = screen.getByTestId("macro-overview-transmission");
    expect(within(panel).getByText("Answers for")).toBeTruthy();
    expect(within(panel).getByText("Computed")).toBeTruthy();
  });
});

describe("OverviewDesk — replay", () => {
  it("withholds everything but the diagnosis when the API ignored the date", () => {
    // `answered_after` on a `/api/macro/*` route can only mean `as_of` was not applied —
    // the query's own bound IS the answer's `as_of`. And a parameter dropped on one of
    // these five reads was dropped on all five, so everything else would be today's desk
    // under a replay heading.
    render(
      <OverviewDesk
        domains={slots({
          usd: dom(D.usd, {
            verdict: {
              kind: "answered_after",
              asOf: "2026-08-24",
              computedAt: "2026-08-27T03:00:00Z",
            },
          }),
        })}
        snapshot={snap(snapshot(), {
          verdict: {
            kind: "replaying",
            asOf: "2026-08-24",
            computedAt: "2026-08-24T07:40:00Z",
          },
        })}
      />,
    );
    expect(screen.getByTestId("macro-overview-wrong-instant")).toBeTruthy();
    expect(screen.queryByTestId("macro-overview-daily-loop")).toBeNull();
    expect(screen.queryByTestId("macro-overview-contradictions")).toBeNull();
    expect(screen.queryByTestId(/^macro-domain-/)).toBeNull();
    // The diagnosis stays: it is the only thing that says which publisher misbehaved.
    expect(screen.getByTestId("macro-overview-transmission")).toBeTruthy();
  });

  it("does NOT withhold when a domain simply had no state at that instant", () => {
    // `unanswered` is that domain's own honest answer, not an API defect. Blanking the tab
    // for it would destroy the only thing tab 00 is for — showing which of the five
    // answered.
    render(
      <OverviewDesk
        domains={slots({
          gold: dom(null, {
            verdict: { kind: "unanswered", asOf: "2026-08-24" },
          }),
        })}
        snapshot={snap(snapshot(), {
          verdict: {
            kind: "replaying",
            asOf: "2026-08-24",
            computedAt: "2026-08-24T07:40:00Z",
          },
        })}
      />,
    );
    expect(screen.queryByTestId("macro-overview-wrong-instant")).toBeNull();
    expect(screen.getByTestId("macro-overview-daily-loop")).toBeTruthy();
    expect(screen.getByTestId("macro-health-gold").textContent).toMatch(
      /none at that instant/i,
    );
  });

  it("names the instant the store answered for, never the one that was asked for", () => {
    render(
      <OverviewDesk
        domains={slots()}
        snapshot={snap(snapshot(), {
          verdict: {
            kind: "replaying",
            asOf: "2026-08-24",
            computedAt: "2026-08-22T07:40:00Z",
          },
        })}
      />,
    );
    const status = screen.getByTestId("macro-replay-status");
    expect(status.getAttribute("data-replay-state")).toBe("replaying");
    // REWORDED 2026-08-29 when tab 00 landed beside tabs 03-05.
    //
    // This asserted "answers for 2026-08-22", against an `answerClock` prop that no
    // longer exists: `ReplayStatus` was rebuilt around one copy family per CLOCK
    // (`instant` / `obs_date`) taken from the tab's registry entry, and the instant
    // family says "was computed".
    //
    // The claim the test was defending survives, and is stronger now, because it moved
    // into the caller. `OverviewTab` used to pass `as_of` in the field named `computedAt`
    // to buy the old wording, which meant one instant printed under the other's name. It
    // now passes both separately — `as_of` to the gate, the real `computed_at` (and the
    // snapshot's `assembled_at`) to the sentence — so BOTH instants are named correctly:
    // the day the answer stands for, and when it was built. A state recomputed after the
    // instant it answers for is still shown, which is the behaviour that mattered.
    expect(status.textContent).toMatch(/at the end of 2026-08-24 UTC/);
    expect(status.textContent).toMatch(/was computed 2026-08-22 07:40 UTC/);
  });

  it("shows no replay chrome at all when the desk is live", () => {
    render(<OverviewDesk domains={slots()} snapshot={snap(snapshot())} />);
    expect(screen.queryByTestId("macro-replay-status")).toBeNull();
    expect(screen.queryByTestId("macro-overview-wrong-instant")).toBeNull();
  });
});

describe("OverviewDesk — what it may never say", () => {
  it("never prints a duration stance, restated or otherwise", () => {
    // Settled by the operator 2026-08-28 (plan §10-I): `BUY`/`SELL` may print where the
    // model produced it — inside the quarantined legacy RatesScorecard on tab 02 — and
    // nowhere else. Tab 00 is named in that ruling, and it fetches neither of the two
    // endpoints that carry `duration_stance`, so the field is not even in reach.
    const { container } = render(
      <OverviewDesk domains={slots()} snapshot={snap(snapshot())} />,
    );
    const text = container.textContent ?? "";
    expect(text).not.toMatch(/\bbuy\b|\bsell\b|duration stance|position size/i);
  });

  it("shows the confidence terms for all four domains, sorted by kind", () => {
    // The lift's whole point: the strip was private to the rates page, so the rates state
    // was the only one of four whose confidence a reader could argue with.
    render(<OverviewDesk domains={slots()} snapshot={NO_SNAPSHOT} />);
    for (const domain of ["inflation", "policy_rates", "usd", "gold"]) {
      expect(screen.getByTestId(`macro-confidence-${domain}`)).toBeTruthy();
    }
    const rates = screen.getByTestId("macro-confidence-policy_rates");
    // The informational terms are shown, and shown APART from the drags — they are not in
    // the confidence product at all, so ranking them beside the multiplicands invites
    // reading a count as a factor.
    expect(rates.textContent).toMatch(/market factors absent/i);
    expect(rates.textContent).toMatch(/sub state confidence:supply/i);

    // AND the fixture is the receipt for §4.1 still being live in production. It is a REAL
    // `/api/macro/rates` response frozen 2026-08-23, and it carries
    // `market_path_is_a_shadow` with `value: 0` and `kind: "multiplicand"` — so the strip
    // correctly renders "market path is a shadow ×0.00" as something that reduced a
    // confidence of 0.85, which it did not: the term is not in the product.
    //
    // That is not a defect in this component. P0 fixed the KIND at the producer
    // (`macro/rates.py:538`, `kind="informational"`), but P0 is a working-tree change
    // riding P2 and has not been released, so the deployed `argon-app` still emits the old
    // kind — `reference_code_default_is_not_deployed_state`, one level up. The strip sorts
    // on `kind` alone and must not special-case the term by name, so it will keep printing
    // this until the API image ships the fix, and then stop with no web change at all.
    // This assertion is here so that flip is visible rather than silent.
    expect(rates.textContent).toMatch(/market path is a shadow ×0\.00/);
  });
});
