import Link from "next/link";

import { CaseCards } from "@/components/fundamentals/CaseCards";
import { CaseFunnels } from "@/components/fundamentals/CaseFunnels";
import { CaseStageTables } from "@/components/fundamentals/CaseStageTables";
import {
  Lede,
  MONO,
  PanelError,
  labelStyle,
} from "@/components/fundamentals/DeskSection";
import { api } from "@/lib/api";
import { SECTION } from "@/lib/fundamentalsSection";

export const dynamic = "force-dynamic";

/**
 * Question 3 — does the money transmit?
 *
 * BOTH CASES LIVE ON THIS ONE ROUTE, DELIBERATELY. The funnels are drawn on a
 * shared radius scale, and the shared scale IS the finding: one chain flares
 * open and the other stays a cylinder under the same capital expenditure.
 * Split across `/cases/optical` and `/cases/datacenter`, each page would
 * compute a scale from its own population, the two silhouettes would stop
 * being comparable, and nothing on either screen would show it. So there is
 * one request, one scale, and one page.
 *
 * This route is a STATIC segment and therefore wins over the sibling
 * `[...node]` catch-all that serves per-chain deep dives. A taxonomy chain
 * literally named `cases` would be shadowed by it; no such chain exists, and
 * the collision is worth knowing about before one is added.
 */
export default async function AiSemiCasesPage() {
  let cases;
  let error: string | null = null;
  try {
    cases = await api.deskCases(SECTION);
  } catch (e) {
    error = e instanceof Error ? e.message : "unknown API error";
  }

  return (
    <main
      style={{ margin: "0 auto", maxWidth: 1180, padding: "24px 20px 64px" }}
    >
      <div style={{ ...labelStyle, letterSpacing: 1.8 }}>
        <Link
          href="/fundamentals/ai-semi"
          style={{ color: "var(--text-muted)" }}
        >
          AI chain desk
        </Link>{" "}
        / question 3
      </div>
      <h1
        style={{
          marginTop: 8,
          fontFamily: MONO,
          fontSize: 24,
          fontWeight: 800,
          letterSpacing: 1.3,
          textTransform: "uppercase",
          color: "var(--text-primary)",
        }}
      >
        Does it transmit?
      </h1>

      <Lede>
        Level 1 places the chains but draws no arrows between them. Some
        sub-chains in the taxonomy are different: their stages carry an explicit
        order, so a dollar&apos;s path through them is structure, not inference.
        They were not picked for being interesting
        {cases ? (
          <>
            {" "}
            — the taxonomy ranks the stages of{" "}
            <strong style={{ color: "var(--text-primary)" }}>
              {cases.length}
            </strong>{" "}
            {cases.length === 1 ? "chain" : "chains"} today, and every one of
            them is drawn below
          </>
        ) : null}
        . Where the taxonomy does not rank stages, drawing a flow would invent
        the arrows the chain map deliberately refuses to draw.
      </Lede>

      {error !== null ? (
        <PanelError what="Cases" error={error} />
      ) : (
        <>
          <CaseCards cases={cases!} />

          <h2
            style={{
              marginTop: 40,
              fontFamily: MONO,
              fontSize: 14,
              fontWeight: 800,
              letterSpacing: 1.2,
              textTransform: "uppercase",
              color: "var(--text-primary)",
            }}
          >
            The funnel
          </h2>
          <Lede>
            Each ring is one stage. Its{" "}
            <strong style={{ color: "var(--text-primary)" }}>
              radius is that stage&apos;s median revenue growth
            </strong>{" "}
            — and both cases are drawn on one shared scale, so the two objects
            are directly comparable. The customer sits on top; the dollar
            travels downward. A chain that amplifies flares open toward the
            bottom. A chain that absorbs stays a cylinder.
          </Lede>
          <CaseFunnels cases={cases!} />

          <h2
            style={{
              marginTop: 40,
              fontFamily: MONO,
              fontSize: 14,
              fontWeight: 800,
              letterSpacing: 1.2,
              textTransform: "uppercase",
              color: "var(--text-primary)",
            }}
          >
            Stage detail
          </h2>
          <CaseStageTables cases={cases!} />
        </>
      )}
    </main>
  );
}
