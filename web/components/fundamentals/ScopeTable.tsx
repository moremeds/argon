/**
 * The boundary — what this desk deliberately does not cover.
 *
 * These groups are NOT "unclassified" and NOT a residual. They are the desk's
 * own organising tags for names held for reasons that have nothing to do with
 * the AI chain, and they keep their own names here. Calling them unclassified
 * would describe an absence in Argon as an absence in the world.
 *
 * The membership counts are computed as the complement of the section's own
 * domains, so the boundary cannot drift from the taxonomy it describes. The
 * REASON each group is out of scope is editorial and lives here, keyed by
 * chain, with a fallback that says the honest generic thing.
 */

import type { ScopeGroup } from "@/lib/api";

import { DASH } from "@/lib/fundamentals/desk";

import { MONO, Note, labelStyle, panelStyle } from "./DeskSection";

/** Groups that are portfolio-construction tags rather than industrial chains
 *  — they have no stages to order, so modelling them as supply chains would
 *  be a category error rather than merely unbuilt work. */
const PORTFOLIO_TAGS = new Set(["Sector-ETF", "M7", "Beta", "Macro"]);

/** Adjacent compute demand: real industries, but the taxonomy defines no
 *  ranked stages for them, so no flow can be drawn. */
const ADJACENT = new Set(["Crypto", "Space", "Quantum"]);

function reason(chain: string): string {
  if (PORTFOLIO_TAGS.has(chain))
    return `A portfolio-construction tag, not an industrial chain ${DASH} it has no stages to order.`;
  if (ADJACENT.has(chain))
    return "Adjacent compute demand, but the taxonomy defines no ranked stages for it, so no flow can be drawn.";
  return "A different industry. No supply relationship to AI capital expenditure is modelled.";
}

const th: React.CSSProperties = {
  ...labelStyle,
  textAlign: "left",
  padding: "9px 12px",
  borderBottom: "1px solid var(--border-dim)",
};

const td: React.CSSProperties = {
  padding: "9px 12px",
  borderBottom: "1px solid var(--border-dim)",
  fontSize: 12,
  color: "var(--text-secondary)",
};

export function ScopeTable({ groups }: { groups: ScopeGroup[] }) {
  if (groups.length === 0) {
    return (
      <Note>
        Every group in the active taxonomy sits inside this section, so the desk
        has no boundary to draw.
      </Note>
    );
  }
  return (
    <div data-testid="desk-scope">
      <div style={{ ...panelStyle, marginTop: 16, overflowX: "auto" }}>
        <table
          style={{ width: "100%", borderCollapse: "collapse", minWidth: 560 }}
        >
          <thead>
            <tr>
              <th style={th}>Group</th>
              <th style={{ ...th, textAlign: "right" }}>Names</th>
              <th style={th}>Why it is out of scope</th>
            </tr>
          </thead>
          <tbody>
            {groups.map((g) => (
              <tr key={g.chain}>
                <td
                  style={{
                    ...td,
                    fontFamily: MONO,
                    color: "var(--text-primary)",
                    whiteSpace: "nowrap",
                  }}
                >
                  {g.chain}
                </td>
                <td
                  style={{
                    ...td,
                    textAlign: "right",
                    fontFamily: MONO,
                    fontVariantNumeric: "tabular-nums",
                  }}
                >
                  {g.members}
                </td>
                <td style={td}>{reason(g.chain)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Note>
        Several of these {DASH} <span style={{ fontFamily: MONO }}>M7</span>,{" "}
        <span style={{ fontFamily: MONO }}>Sector-ETF</span>,{" "}
        <span style={{ fontFamily: MONO }}>Beta</span> {DASH} are not industrial
        chains at all. Modelling them as supply chains would be a category
        error, which is the substantive reason they sit outside this desk rather
        than merely unbuilt.
      </Note>
    </div>
  );
}
