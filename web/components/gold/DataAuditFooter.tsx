import type { components } from "@/lib/types";

type Provenance = components["schemas"]["GoldInputProvenance"];

type Props = {
  obsDate: string;
  computedAt: string;
  inputsUsed: Record<string, Provenance>;
};

// An input the orchestrator declared but did not consume. Rendered apart from the ones
// it did, because "obs null · as_of null" reads as broken data when the truth is a
// recorded decision — and the manifest this footer draws used to name four inputs out of
// twelve, which read as a complete audit trail. Showing both counts is the point.
function isOmitted(prov: Provenance): boolean {
  return !prov.obs_date;
}

export function DataAuditFooter({ obsDate, computedAt, inputsUsed }: Props) {
  const entries = Object.entries(inputsUsed);
  const read = entries.filter(([, prov]) => !isOmitted(prov));
  const omitted = entries.filter(([, prov]) => isOmitted(prov));
  return (
    <footer
      style={{
        padding: "16px 24px",
        borderTop: "1px solid var(--border-dim, #1b2030)",
        color: "var(--text-muted, #6b7280)",
        fontFamily: "var(--font-mono)",
        fontSize: 10,
        letterSpacing: 1.2,
        textTransform: "uppercase",
      }}
    >
      <div>
        LENS HEURISTICS · v1 · obs {obsDate} · computed {computedAt}
        {entries.length > 0 && (
          <>
            {" "}
            · INPUTS {read.length}/{entries.length} READ
          </>
        )}
      </div>
      {read.length > 0 && (
        <ul
          style={{
            margin: "8px 0 0",
            paddingLeft: 18,
            listStyle: "square",
            columns: 3,
            columnGap: 32,
          }}
        >
          {read.map(([sid, prov]) => (
            <li key={sid}>
              {sid}
              {prov.lens && prov.lens.length > 0 && (
                <> [{prov.lens.join("/")}]</>
              )}{" "}
              · obs {prov.obs_date} · as_of {String(prov.as_of).slice(0, 19)}
            </li>
          ))}
        </ul>
      )}
      {omitted.length > 0 && (
        <ul
          data-testid="gold-audit-omissions"
          style={{
            margin: "8px 0 0",
            paddingLeft: 18,
            listStyle: "square",
            color: "var(--text-dim, #4b5563)",
          }}
        >
          {omitted.map(([sid, prov]) => (
            <li key={sid} title={prov.omission_reason ?? undefined}>
              {sid}
              {prov.lens && prov.lens.length > 0 && (
                <> [{prov.lens.join("/")}]</>
              )}{" "}
              · NOT READ
              {prov.omission_reason && (
                <span style={{ textTransform: "none", letterSpacing: 0 }}>
                  {" "}
                  — {prov.omission_reason}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </footer>
  );
}
