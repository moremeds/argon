import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { OverviewDesk } from "@/components/macro/OverviewDesk";
import type {
  DeltaSeries,
  DomainWeek,
} from "@/components/macro/overview/zone1";
import type { ReplayVerdict } from "@/components/macro/replay";
import type {
  MacroContextSnapshot,
  MacroDomainKey,
  MacroDomainState,
  MacroOverviewSlot,
} from "@/components/macro/types";
import type { components } from "@/lib/types";
import FIXTURE from "../fixtures/macroDomainStates.json";
import {
  POLICY_COMPARISON,
  POLICY_COMPARISON_WITH_MARKET_PATH,
} from "./rates/fixture";

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
type PolicyComparison = components["schemas"]["PolicyComparison"];

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

/**
 * `OverviewDesk` with only the two publishers most of these assertions are about.
 *
 * Tab 00 gained six more props when it was rebound to the board's own structure (the
 * week-over-week pair, the policy comparison, the market-delta series, the gold gauge and
 * the two window labels). Every one of them is REQUIRED on the component, deliberately —
 * a default would let a wiring bug ship as an empty panel — so the defaults live here in
 * the test instead, where "this assertion is not about the deltas" is the honest reading.
 *
 * The defaults are all EMPTY rather than populated: a test that does not name a publisher
 * should see that publisher's absent state, not a fixture it did not ask for. The panels
 * that read them render their own three-state copy, which is what several assertions below
 * (the chrome scan in particular) actually depend on.
 */
function Desk(props: {
  domains: DomainSlots;
  snapshot: MacroOverviewSlot<MacroContextSnapshot>;
  week?: DomainWeek;
  policy?: { value: PolicyComparison | null; error?: string };
  deltas?: DeltaSeries[];
  gauge?: { value: null; error?: string };
}) {
  const {
    domains,
    snapshot: snapshotSlot,
    week,
    policy,
    deltas,
    gauge,
  } = props;
  return (
    <OverviewDesk
      domains={domains}
      snapshot={snapshotSlot}
      // No prior-week read by default: the state-flip panel then says it had nothing to
      // compare against, which is the correct three-state answer and not a silent "no flip".
      week={
        week ?? {
          inflation: { now: domains.inflation, prior: { value: null } },
          policy_rates: { now: domains.policy_rates, prior: { value: null } },
          usd: { now: domains.usd, prior: { value: null } },
          gold: { now: domains.gold, prior: { value: null } },
        }
      }
      policy={policy ?? { value: null }}
      deltas={deltas ?? []}
      gauge={gauge ?? { value: null }}
      priorLabel="08-17"
      nowLabel="08-24"
      windowLabel="1 week"
    />
  );
}

describe("OverviewDesk — artifact panel contract", () => {
  it("renders the exact eleven-panel inventory in order", () => {
    const { container } = render(
      <Desk domains={slots()} snapshot={snap(snapshot())} />,
    );
    expect(
      [...container.querySelectorAll(".panel > .panel-h h3")].map(
        (node) => node.textContent,
      ),
    ).toEqual([
      "State flips × confidence moves",
      "Market deltas · 1 week",
      "Anchor letting go · gauge corr_60d",
      "Four policy paths · who says what",
      "Contradiction feed · engine-reported",
      "Cross-domain contradictions · this week",
      "Transmission health · measured link strength",
      "FOMC calendar × what the market prices",
      "Confidence repair · what each event fixes",
      "Off-chain dimension · Energy (proposal)",
      "Boundary · what is NOT on this desk",
    ]);
  });
});

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

describe("OverviewDesk — market-implied probability bars", () => {
  it("renders the same live Frenzy meeting bars as the Fed tab", () => {
    render(
      <Desk
        domains={slots()}
        snapshot={NO_SNAPSHOT}
        policy={{ value: POLICY_COMPARISON_WITH_MARKET_PATH }}
      />,
    );

    const panel = screen.getByTestId("board-panel-fomc-calendar");
    expect(
      within(panel).getAllByTestId("market-implied-probability-bar"),
    ).toHaveLength(3);
    expect(
      within(panel).queryByTestId("macro-market-implied-refusal"),
    ).toBeNull();
    expect(panel.textContent).toContain("Hike 25 bp · 55.7 %");
    expect(panel.textContent).toContain("Hold · 44.3 %");
    expect(panel.textContent).toContain("frenzy_capital");
  });

  it("keeps the publisher refusal when the market path is absent", () => {
    render(
      <Desk
        domains={slots()}
        snapshot={NO_SNAPSHOT}
        policy={{ value: POLICY_COMPARISON }}
      />,
    );

    const refusal = screen.getByTestId("macro-market-implied-refusal");
    expect(refusal.textContent).toContain(
      "optional third-party shadow and is not enabled",
    );
    expect(
      screen.queryByTestId("market-implied-probability-bar"),
    ).toBeNull();
  });
});

describe("OverviewDesk — the four domain states", () => {
  it("renders the four domains in causal order, not as four peers", () => {
    render(<Desk domains={slots()} snapshot={NO_SNAPSHOT} />);
    const cards = screen.getAllByTestId(/^macro-domain-/);
    expect(cards.map((c) => c.getAttribute("data-testid"))).toEqual([
      "macro-domain-inflation",
      "macro-domain-policy_rates",
      "macro-domain-usd",
      "macro-domain-gold",
    ]);
  });

  it("shows each domain's state and direction", () => {
    render(<Desk domains={slots()} snapshot={NO_SNAPSHOT} />);
    const usd = screen.getByTestId("macro-domain-usd");
    expect(within(usd).getByText("RANGEBOUND")).toBeTruthy();
    expect(within(usd).getByText(/FLAT/)).toBeTruthy();
  });

  it("names a domain that failed to load rather than blanking it", () => {
    render(
      <Desk
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
      <Desk domains={slots({ gold: dom(null) })} snapshot={NO_SNAPSHOT} />,
    );
    const gold = screen.getByTestId("macro-domain-gold");
    expect(within(gold).getByText(/no state has been computed/i)).toBeTruthy();
  });

  // RE-POINTED 2026-08-29 with the board's own structure. The contradictions used to hang
  // off each domain card; the board gathers them into one zone-2 panel instead, because an
  // operator scanning for what broke overnight should not have to open four cards to find
  // out that nothing did. The invariant is unchanged — a contradiction is never hidden
  // behind the state that carries it — and it is now checked where they actually live.
  it("surfaces contradictions instead of hiding them behind the state", () => {
    render(<Desk domains={slots()} snapshot={NO_SNAPSHOT} />);
    const feed = screen.getByTestId("board-panel-contradictions");
    // The frozen inflation state carries 2 contradictions.
    expect(
      within(feed).getAllByTestId("macro-contradiction-row-inflation"),
    ).toHaveLength(2);
  });

  it("reports the evidence count so a conclusion is never shown bare", () => {
    render(<Desk domains={slots()} snapshot={NO_SNAPSHOT} />);
    const usd = screen.getByTestId("macro-domain-usd");
    expect(
      within(usd).getByTestId("macro-evidence-count-usd").textContent,
    ).toMatch(/\d/);
  });

  // The ban is on the DESK synthesizing a verdict of its own. It is deliberately not a
  // blunt substring scan: the gold engine's own note reads "the valuation lens is a
  // warning: it never becomes a price target, an allocation, or a size", and a plain
  // /allocat/i match flags that disclaimer as if it were a recommendation.
  //
  // WIDENED 2026-08-29, for the same reason one level up. `/composite/i` was on this list
  // and the board's own standfirst is "There is not, and will never be, a composite
  // score" — so the blunt pattern failed on the sentence that states the invariant. The
  // word is banned as a THING PRESENTED, not as a word; and because a refusal is now the
  // only legal way for it to appear, the test also requires it to appear, which the flat
  // ban could never do.
  it("adds no master score of its own to the desk chrome", () => {
    const { container } = render(
      <Desk domains={noDomains()} snapshot={NO_SNAPSHOT} />,
    );
    const text = container.textContent ?? "";
    for (const banned of [
      /master score/i,
      /overall score/i,
      /composite (score|reading|index|value)\s*(of|:|=|\d)/i,
      // An allocation with a NUMBER attached is the thing being banned. The bare word is
      // now unavoidable: the boundary panel refuses one in as many words, which is the
      // trap this test's own comment describes for the gold engine's disclaimer.
      /allocat\w*\s*(of|to|:|=)?\s*\d/i,
      /target weight/i,
      /probability of/i,
    ]) {
      expect(text).not.toMatch(banned);
    }
    // The refusals themselves must be on the page. A desk that silently omits a composite
    // and a desk that has decided never to publish one look identical without these.
    expect(text).toMatch(/will never be, a composite score/i);
    expect(text).toMatch(/No composite\./i);
    expect(text).toMatch(/no allocation on this desk/i);
  });

  it("renders exactly one state per domain and no fifth aggregate", () => {
    render(<Desk domains={slots()} snapshot={NO_SNAPSHOT} />);
    expect(screen.getAllByTestId(/^macro-domain-/)).toHaveLength(4);
    expect(screen.queryByTestId(/score|composite|aggregate/i)).toBeNull();
  });

  it("shows the engine version, because two engines are two semantics", () => {
    render(<Desk domains={slots()} snapshot={NO_SNAPSHOT} />);
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
    render(<Desk domains={slots()} snapshot={snap(snapshot())} />);
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
      <Desk
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
      <Desk
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
      <Desk
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
    render(<Desk domains={slots()} snapshot={NO_SNAPSHOT} />);
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
      <Desk
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
      <Desk
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

// RE-POINTED 2026-08-29 from a table to the chain rail.
//
// Tab 00 used to open with a "daily loop" table — the four domains, one row each. The
// board does not have one: the four answers appear ONCE, as the nodes of the transmission
// rail at the anchor of the tab, and the three zones above are the evidence for them. A
// table of the same four states above the rail is the second rendering the zones exist to
// replace, so it was deleted rather than kept beside its own replacement.
//
// Every assertion below survived that move, because none of them was about a table: the
// engine's causal order, the absence of a fifth summarising row, and the three states kept
// apart are properties of how the four domains are PRESENTED, whatever the shape.
describe("OverviewDesk — the transmission rail", () => {
  it("lists the four domains in the ENGINE's causal order, not the tab strip's", () => {
    render(<Desk domains={slots()} snapshot={NO_SNAPSHOT} />);
    const rail = screen.getByTestId("macro-chain-rail");
    const nodes = within(rail).getAllByTestId(/^macro-domain-/);
    expect(nodes.map((n) => n.getAttribute("data-testid"))).toEqual([
      "macro-domain-inflation",
      "macro-domain-policy_rates",
      "macro-domain-usd",
      "macro-domain-gold",
    ]);
  });

  it("adds no fifth node summarising the four", () => {
    render(<Desk domains={slots()} snapshot={NO_SNAPSHOT} />);
    const rail = screen.getByTestId("macro-chain-rail");
    expect(within(rail).getAllByTestId(/^macro-domain-/)).toHaveLength(4);
    // Three arrows for four nodes. A fourth arrow would mean something follows gold.
    expect(rail.querySelectorAll(".arrow")).toHaveLength(3);
  });

  it("keeps the three states apart per node", () => {
    render(
      <Desk
        domains={slots({
          gold: dom(null, {
            error: "The gold state API request failed: ECONNREFUSED",
          }),
          usd: dom(null),
        })}
        snapshot={NO_SNAPSHOT}
      />,
    );
    expect(screen.getByTestId("macro-domain-gold").textContent).toMatch(
      /ECONNREFUSED/,
    );
    expect(screen.getByTestId("macro-domain-usd").textContent).toMatch(
      /engine has not run/i,
    );
  });

  it("says how many nodes answered, so a short rail cannot read as a broken chain", () => {
    render(
      <Desk
        domains={slots({ gold: dom(null), usd: dom(null) })}
        snapshot={NO_SNAPSHOT}
      />,
    );
    expect(
      screen.getByTestId("macro-chain-rail").parentElement?.textContent,
    ).toMatch(/2 of 4 nodes answered/i);
  });
});

describe("OverviewDesk — the contradiction feed", () => {
  it("gathers every domain's contradictions and attributes each one", () => {
    render(<Desk domains={slots()} snapshot={NO_SNAPSHOT} />);
    const feed = screen.getByTestId("board-panel-contradictions");
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
      <Desk
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
    render(<Desk domains={slots()} snapshot={NO_SNAPSHOT} />);
    const feed = screen.getByTestId("board-panel-contradictions");
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
    render(<Desk domains={noDomains()} snapshot={NO_SNAPSHOT} />);
    expect(
      screen.getByTestId("board-panel-contradictions").textContent,
    ).toMatch(/nothing was asked, not that nothing fired/i);
  });
});

describe("OverviewDesk — transmission health", () => {
  it("gives every one of the five publishers a row, three-state", () => {
    render(
      <Desk
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
    render(<Desk domains={slots()} snapshot={NO_SNAPSHOT} />);
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
    render(<Desk domains={slots()} snapshot={NO_SNAPSHOT} />);
    const panel = screen.getByTestId("board-panel-transmission");
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
      <Desk
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
    expect(screen.queryByTestId("macro-chain-rail")).toBeNull();
    expect(screen.queryByTestId("board-panel-contradictions")).toBeNull();
    expect(screen.queryByTestId(/^macro-domain-/)).toBeNull();
    // The diagnosis stays: it is the only thing that says which publisher misbehaved.
    expect(screen.getByTestId("board-panel-transmission")).toBeTruthy();
  });

  it("does NOT withhold when a domain simply had no state at that instant", () => {
    // `unanswered` is that domain's own honest answer, not an API defect. Blanking the tab
    // for it would destroy the only thing tab 00 is for — showing which of the five
    // answered.
    render(
      <Desk
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
    expect(screen.getByTestId("macro-chain-rail")).toBeTruthy();
    expect(screen.getByTestId("macro-health-gold").textContent).toMatch(
      /none at that instant/i,
    );
  });

  it("names the instant the store answered for, never the one that was asked for", () => {
    render(
      <Desk
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
    render(<Desk domains={slots()} snapshot={snap(snapshot())} />);
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
      <Desk domains={slots()} snapshot={snap(snapshot())} />,
    );
    const text = container.textContent ?? "";
    expect(text).not.toMatch(/\bbuy\b|\bsell\b|duration stance|position size/i);
  });

  it("shows the confidence terms for all four domains, sorted by kind", () => {
    // The lift's whole point: the strip was private to the rates page, so the rates state
    // was the only one of four whose confidence a reader could argue with.
    render(<Desk domains={slots()} snapshot={NO_SNAPSHOT} />);
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
