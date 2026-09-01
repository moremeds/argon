import { notFound } from "next/navigation";
import Link from "next/link";

import { CapexPanel } from "@/components/fundamentals/CapexPanel";
import { ChainCalendar } from "@/components/fundamentals/ChainCalendar";
import { ChainMapPanel } from "@/components/fundamentals/ChainMapPanel";
import { DeltaRail } from "@/components/fundamentals/DeltaRail";
import { DeskLimits } from "@/components/fundamentals/DeskLimits";
import {
  DeskMasthead,
  QUESTION_TOKENS,
} from "@/components/fundamentals/DeskMasthead";
import {
  DeskSection,
  Lede,
  MONO,
  Note,
  PanelError,
  labelStyle,
} from "@/components/fundamentals/DeskSection";
import { ScopeTable } from "@/components/fundamentals/ScopeTable";
import { ValuationPanel } from "@/components/fundamentals/ValuationPanel";
import { api } from "@/lib/api";
import { chainPoints, valuationMarks } from "@/lib/fundamentals/desk";
import { SECTION } from "@/lib/fundamentalsSection";

export const dynamic = "force-dynamic";

function message(error: unknown): string {
  return error instanceof Error ? error.message : "unknown API error";
}

/** Resolve to a value OR an error, never to a rejection.
 *
 *  EVERY panel settles independently and on purpose. The desk's job is to show
 *  which halves of the picture it holds, so one endpoint failing must leave the
 *  others standing — a page-level `Promise.all` rejection would replace a
 *  partial answer with no answer, which is strictly less information.
 *
 *  The error must then reach the component. A failed request rendered through
 *  `?? []` becomes an affirmative coverage claim manufactured out of a failure. */
async function settle<T>(
  p: Promise<T>,
): Promise<
  { value: T; error?: undefined } | { value?: undefined; error: unknown }
> {
  try {
    return { value: await p };
  } catch (error) {
    return { error };
  }
}

/**
 * Level 1 of the AI/semi chain desk — the question ladder, in order.
 *
 * The section order is the argument and is fixed: capex, then the chain map,
 * then valuation, then limits. Question three cannot be answered before
 * question one, so this page is a SCROLL and not a tab bar — six tabs each
 * refetching a fifth of the same answer would make the panels look independent
 * when they share one as-of and one dependency chain.
 *
 * There is no `/fundamentals` universe index above this route; `/fundamentals`
 * redirects here. A chooser listing one choice implies siblings that do not
 * exist, and the desk would look like it covers a universe it does not.
 */
export default async function AiSemiDeskPage() {
  const [capex, matrix, limits, scope, delta, calendar] = await Promise.all([
    settle(api.deskCapex(SECTION)),
    settle(api.deskMatrix(SECTION)),
    settle(api.deskLimits(SECTION)),
    settle(api.deskScope(SECTION)),
    settle(api.deskDelta(SECTION)),
    settle(api.deskCalendar(SECTION)),
  ]);

  // `deskCalendar` allows a 404 through as null, because the node page passes a
  // chain that may not exist. Here the section is fixed, so a null means THIS
  // SECTION is not registered — a different fact from an empty desk, and one
  // that must not render as "nothing is happening in AI/semi".
  if (calendar.value === null) notFound();

  const cells = matrix.value?.cells ?? [];
  // `null`, not `0`, when the matrix never arrived. `?? []` is the right shape
  // for a component that renders an empty LIST, and the wrong shape for a
  // headline COUNT: it turns "we could not ask" into "we asked and the answer
  // was none", which is the one substitution this desk exists to refuse.
  const points = matrix.value ? chainPoints(cells) : null;
  const placed = points ? points.length : null;
  const universe = matrix.value ? valuationMarks(cells).universe : null;
  const layers = points ? new Set(points.map((p) => p.layer)).size : null;

  return (
    <main
      style={{ margin: "0 auto", maxWidth: 1180, padding: "24px 20px 64px" }}
    >
      <DeskMasthead
        chains={placed}
        companies={universe}
        capexQuarters={capex.value ? capex.value.quarters.length : null}
        layers={layers}
      />

      <DeskSection
        index={1}
        title="How is sample capex changing?"
        accent={`var(${QUESTION_TOKENS[0]})`}
        testId="desk-capex"
      >
        <Lede>
          Quarterly capital expenditure for the members of this sample that
          file in USD, in USD bn, beside the same sample&apos;s capex as a share
          of its own revenue. The sample is a taxonomy chain, not the full set
          of AI buyers, and it is not the same sample as the case groups below.
        </Lede>
        {capex.error ? (
          <PanelError what="Capex" error={message(capex.error)} />
        ) : (
          <CapexPanel data={capex.value!} />
        )}
      </DeskSection>

      <DeskSection
        index={2}
        title="How do industry groups compare?"
        accent={`var(${QUESTION_TOKENS[1]})`}
        testId="desk-chain-map"
      >
        <Lede>
          A PM needs three things about each chain at once — how fast it is
          growing, how well it is paid, and where it sits in the taxonomy — and
          any two of those on a flat chart hides the third. So the map is
          dimensional:{" "}
          <strong style={{ color: "var(--text-primary)" }}>drag it.</strong>{" "}
          Revenue growth (TTM YoY) runs left-to-right, reported gross margin
          (latest quarter) runs into the depth, and the taxonomy layers are the
          stacked planes. Each chain figure is the equal-weight median of its
          members carrying that metric.
        </Lede>
        {matrix.error ? (
          <PanelError what="Chain map" error={message(matrix.error)} />
        ) : (
          <ChainMapPanel cells={cells} limits={limits.value ?? null} />
        )}
      </DeskSection>

      <DeskSection
        index={3}
        title="How do case groups compare?"
        accent={`var(${QUESTION_TOKENS[2]})`}
        testId="desk-cases-link"
      >
        <Lede>
          The map places chains but draws no arrows between them. Some
          sub-chains in the taxonomy carry an explicit stage order, so their
          groups can be laid out side by side on one shared scale. The order is
          the taxonomy&apos;s, not a traced procurement chain.
        </Lede>
        <p style={{ marginTop: 14 }}>
          <Link
            href="/fundamentals/ai-semi/cases"
            style={{
              ...labelStyle,
              display: "inline-block",
              padding: "8px 14px",
              borderRadius: 4,
              background: "var(--accent-bg)",
              color: "var(--accent-text)",
              letterSpacing: 1.2,
              textDecoration: "none",
            }}
          >
            Open the case groups →
          </Link>
        </p>
      </DeskSection>

      <DeskSection
        index={4}
        title="Where is valuation versus own history?"
        accent={`var(${QUESTION_TOKENS[3]})`}
        testId="desk-valuation"
      >
        <Lede>
          One rule governs this section, and it comes from measurement rather
          than taste: valuation in this store{" "}
          <strong style={{ color: "var(--text-primary)" }}>
            times a name against its own history
          </strong>{" "}
          (within-ticker <span style={{ fontFamily: MONO }}>sales_to_ev</span>{" "}
          IC +0.0744, t 5.77) and{" "}
          <strong style={{ color: "var(--text-primary)" }}>
            inverts across names
          </strong>{" "}
          (cross-sectional{" "}
          <span style={{ fontFamily: MONO }}>book_to_price</span> IC −0.0365, t
          −2.32, both frozen from the 2026-08-12 valuation-anchors study rather
          than recomputed here). So the desk shows each name&apos;s percentile
          against itself and offers no way to sort the column. Ranking here
          would be selling a measured negative as a signal.
        </Lede>
        {matrix.error ? (
          <PanelError what="Valuation" error={message(matrix.error)} />
        ) : (
          <ValuationPanel cells={cells} />
        )}
      </DeskSection>

      <DeskSection
        index={5}
        title="What are the data limits?"
        accent={`var(${QUESTION_TOKENS[4]})`}
        testId="desk-limits-section"
      >
        <Lede>
          The measured boundaries of the readings above: what the store does
          not hold, what a median leaves out, and what a percentile is not.
        </Lede>
        {limits.error ? (
          <PanelError what="Limits" error={message(limits.error)} />
        ) : (
          <DeskLimits data={limits.value!} />
        )}
      </DeskSection>

      <section style={{ marginTop: 46 }} data-testid="desk-boundary">
        <h2
          style={{
            fontFamily: MONO,
            fontSize: 14,
            fontWeight: 800,
            letterSpacing: 1.2,
            textTransform: "uppercase",
            color: "var(--text-primary)",
          }}
        >
          The boundary
        </h2>
        <Lede>
          The taxonomy holds more than the AI chain. Those other groups are{" "}
          <strong style={{ color: "var(--text-primary)" }}>
            not unclassified and not a residual
          </strong>{" "}
          — they are the desk&apos;s own organising tags for names held for
          reasons that have nothing to do with this chain, and they keep their
          own names here.
        </Lede>
        {scope.error ? (
          <PanelError what="Scope" error={message(scope.error)} />
        ) : (
          <ScopeTable groups={scope.value!} />
        )}
      </section>

      <section style={{ marginTop: 46 }} data-testid="desk-log">
        <h2
          style={{
            fontFamily: MONO,
            fontSize: 14,
            fontWeight: 800,
            letterSpacing: 1.2,
            textTransform: "uppercase",
            color: "var(--text-primary)",
          }}
        >
          Desk log
        </h2>
        <Note>
          Below the argument, not inside it: what Argon learned since you last
          looked, and what prints next. Neither answers a question on the ladder
          — they are how the ladder gets re-asked when the facts move.
        </Note>
        <DeltaRail
          data={delta.value ?? null}
          error={delta.error ? message(delta.error) : undefined}
        />
        <ChainCalendar
          data={calendar.value ?? null}
          error={calendar.error ? message(calendar.error) : undefined}
        />
      </section>
    </main>
  );
}
