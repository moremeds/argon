import type { components } from "@/lib/types";

type Provenance = components["schemas"]["GoldInputProvenance"];

type Props = {
  obsDate: string;
  computedAt: string;
  inputsUsed: Record<string, Provenance>;
};

export function DataAuditFooter({ obsDate, computedAt, inputsUsed }: Props) {
  const entries = Object.entries(inputsUsed);
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
      </div>
      {entries.length > 0 && (
        <ul
          style={{
            margin: "8px 0 0",
            paddingLeft: 18,
            listStyle: "square",
            columns: 3,
            columnGap: 32,
          }}
        >
          {entries.map(([sid, prov]) => (
            <li key={sid}>
              {sid} · obs {prov.obs_date} · as_of{" "}
              {String(prov.as_of).slice(0, 19)}
            </li>
          ))}
        </ul>
      )}
    </footer>
  );
}
