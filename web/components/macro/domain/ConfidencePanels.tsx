import { BoardPanel, MONO_LABEL } from "./BoardPanel";
import {
  confidenceChain,
  fmtConfidence,
  repairTable,
  type ChainTerm,
  type ConfidenceChain,
  type ConfidenceReason,
} from "./confidence";

const VALUE: React.CSSProperties = {
  fontFamily: "var(--font-mono), monospace",
  fontSize: 18,
  fontWeight: 700,
  color: "var(--text-primary)",
  lineHeight: 1.1,
};

const OPERATOR: React.CSSProperties = {
  fontFamily: "var(--font-mono), monospace",
  fontSize: 14,
  color: "var(--text-muted)",
  alignSelf: "center",
};

/** A multiplicand prints as itself; a penalty prints as the subtraction it performs, so
 *  the row reads as one continuous product rather than a mix of two conventions. */
function termFace(t: ChainTerm): string {
  return t.kind === "penalty"
    ? `(1 − ${t.raw.toFixed(2)})`
    : t.factor.toFixed(2);
}

function TermBlock({ t }: { t: ChainTerm }) {
  const degraded = t.factor < 1;
  return (
    <div style={{ minWidth: 92, maxWidth: 200 }}>
      <div style={{ ...VALUE, color: degraded ? "var(--warning)" : undefined }}>
        {termFace(t)}
      </div>
      <div style={{ ...MONO_LABEL, marginTop: 4 }}>
        {t.term.replace(/_/g, " ")}
      </div>
      <div
        style={{
          fontSize: 11,
          color: "var(--text-secondary)",
          marginTop: 2,
          lineHeight: 1.4,
        }}
      >
        {t.detail}
      </div>
    </div>
  );
}

/**
 * Board t3 · "The arithmetic of confidence".
 *
 * Every term, including the ones that did not fire, then the product, then a
 * reconciliation against what the engine published. See `confidence.ts` for why the
 * reconciliation is rendered rather than assumed.
 */
export function ConfidenceArithmeticPanel({
  reasons,
  confidence,
  endpoint,
}: {
  reasons: readonly ConfidenceReason[];
  confidence: string | number | null | undefined;
  /** The route the terms came off, named for the footer. */
  endpoint: string;
}) {
  const chain = confidenceChain(reasons, confidence);

  if (chain.terms.length === 0) {
    return (
      <BoardPanel
        id="confidence-arithmetic"
        title="The arithmetic of confidence"
        questions={["Q7"]}
        basis="REAL"
        source={`${endpoint} · confidence_reasons[]`}
      >
        <p style={{ margin: 0, fontSize: 12, color: "var(--text-muted)" }}>
          This state carries no confidence terms, so its number cannot be
          audited here. That is a gap in the engine&apos;s output, not a
          statement that the confidence is unfounded.
        </p>
      </BoardPanel>
    );
  }

  return (
    <BoardPanel
      id="confidence-arithmetic"
      title={`The arithmetic of confidence · why ${fmtConfidence(chain.reported)}`}
      questions={["Q7"]}
      basis="REAL"
      source={`${endpoint} · confidence_reasons[] — every term as published, including the ones that did not fire`}
    >
      <div
        data-testid="confidence-chain"
        style={{
          display: "flex",
          gap: 12,
          flexWrap: "wrap",
          alignItems: "flex-start",
        }}
      >
        {chain.terms.map((t, i) => (
          <div key={t.term} style={{ display: "flex", gap: 12 }}>
            {i > 0 ? <span style={OPERATOR}>×</span> : null}
            <TermBlock t={t} />
          </div>
        ))}
        <span style={OPERATOR}>=</span>
        <div style={{ minWidth: 92 }}>
          <div style={{ ...VALUE, color: "var(--text-primary)" }}>
            {fmtConfidence(chain.product)}
          </div>
          <div style={{ ...MONO_LABEL, marginTop: 4 }}>confidence</div>
        </div>
      </div>

      <p
        data-testid="confidence-reconciliation"
        style={{
          margin: 0,
          fontSize: 12,
          lineHeight: 1.5,
          color: chain.reconciles ? "var(--text-secondary)" : "var(--negative)",
        }}
      >
        {chain.reconciles ? (
          <>
            The product reproduces the published {fmtConfidence(chain.reported)}{" "}
            digit for digit. Confidence here is auditable multiplication, not a
            score — each term names the evidence that moved it.
          </>
        ) : (
          <>
            These terms multiply to {chain.product.toFixed(4)}, and the engine
            published{" "}
            {chain.reported === null ? "—" : chain.reported.toFixed(4)}. The
            chain does not reproduce the number, so read neither as proof of the
            other until the engine and this page are reconciled.
          </>
        )}
      </p>

      {chain.informational.length > 0 ? (
        <div style={{ display: "grid", gap: 4 }}>
          <div style={MONO_LABEL}>carried, not multiplied</div>
          {chain.informational.map((r) => (
            <div
              key={r.term}
              style={{
                fontSize: 11,
                color: "var(--text-secondary)",
                lineHeight: 1.4,
              }}
            >
              <span style={MONO_LABEL}>{r.term.replace(/_/g, " ")}</span>{" "}
              {r.value} — {r.detail}
            </div>
          ))}
        </div>
      ) : null}
    </BoardPanel>
  );
}

/**
 * Board t3 · "Falsifier window · confidence repair table".
 *
 * The board's boundary, kept: only state/confidence sensitivity, which is computable from
 * the terms already on screen. No event probability and no date — this table says what a
 * repair would be worth, never whether or when it arrives.
 */
export function ConfidenceRepairPanel({
  reasons,
  confidence,
}: {
  reasons: readonly ConfidenceReason[];
  confidence: string | number | null | undefined;
}) {
  const chain: ConfidenceChain = confidenceChain(reasons, confidence);
  const table = repairTable(chain);

  return (
    <BoardPanel
      id="confidence-repair"
      title="Falsifier window · confidence repair table"
      questions={["Q6"]}
      basis="COMPUTED"
      source="the same product shown above, with exactly one term set to its clear value — no probability and no date is estimated here"
    >
      {table.rows.length === 0 ? (
        <p style={{ margin: 0, fontSize: 12, color: "var(--text-secondary)" }}>
          Every term is already at its clear value, so there is nothing to
          repair — this confidence is not being held down by any input on the
          list above.
        </p>
      ) : (
        <table
          data-testid="confidence-repair-table"
          style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}
        >
          <thead>
            <tr>
              <th
                style={{ ...MONO_LABEL, textAlign: "left", paddingBottom: 6 }}
              >
                if this clears
              </th>
              <th
                style={{
                  ...MONO_LABEL,
                  textAlign: "right",
                  paddingBottom: 6,
                  whiteSpace: "nowrap",
                }}
              >
                confidence
              </th>
            </tr>
          </thead>
          <tbody>
            {table.rows.map((row) => (
              <tr key={row.term}>
                <td
                  style={{
                    padding: "5px 0",
                    color: "var(--text-secondary)",
                    borderTop: "1px solid var(--border-dim)",
                    lineHeight: 1.4,
                  }}
                >
                  <span style={MONO_LABEL}>{row.term.replace(/_/g, " ")}</span>{" "}
                  {row.detail}
                </td>
                <td
                  style={{
                    padding: "5px 0",
                    textAlign: "right",
                    whiteSpace: "nowrap",
                    fontFamily: "var(--font-mono), monospace",
                    borderTop: "1px solid var(--border-dim)",
                    color: "var(--text-primary)",
                  }}
                >
                  {fmtConfidence(table.from)} → {fmtConfidence(row.to)}
                </td>
              </tr>
            ))}
            {table.allClear !== null ? (
              <tr>
                <td
                  style={{
                    padding: "5px 0",
                    borderTop: "1px solid var(--border-dim)",
                    ...MONO_LABEL,
                  }}
                >
                  all clear
                </td>
                <td
                  style={{
                    padding: "5px 0",
                    textAlign: "right",
                    whiteSpace: "nowrap",
                    fontFamily: "var(--font-mono), monospace",
                    borderTop: "1px solid var(--border-dim)",
                    color: "var(--text-primary)",
                  }}
                >
                  {fmtConfidence(table.from)} → {fmtConfidence(table.allClear)}
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      )}
    </BoardPanel>
  );
}
