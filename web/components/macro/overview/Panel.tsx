import type { ReactNode } from "react";

/**
 * One titled block on tab 00.
 *
 * Every panel on this tab is a LAYOUT over fields some other tab already renders, so each
 * one carries a lede saying which publisher it is re-presenting. That is not decoration:
 * tab 00 is the slice most able to become new analytics by accident (plan §8), and a panel
 * whose lede cannot name the field it lays out is a panel that computed something.
 */
export function Panel({
  id,
  title,
  lede,
  children,
}: {
  id: string;
  title: string;
  lede: string;
  children: ReactNode;
}) {
  return (
    <section
      id={id}
      data-testid={`macro-overview-${id}`}
      style={{
        background: "var(--bg-panel)",
        border: "1px solid var(--border-dim)",
        borderRadius: 6,
        padding: "16px 18px",
      }}
    >
      <h2
        style={{
          margin: 0,
          fontFamily: "var(--font-mono), monospace",
          fontSize: 11,
          letterSpacing: 1.5,
          textTransform: "uppercase",
          color: "var(--text-primary)",
          fontWeight: 600,
        }}
      >
        {title}
      </h2>
      <p
        style={{
          margin: "5px 0 0",
          fontSize: 12,
          lineHeight: 1.5,
          color: "var(--text-secondary)",
          maxWidth: 780,
        }}
      >
        {lede}
      </p>
      <div style={{ marginTop: 14 }}>{children}</div>
    </section>
  );
}

/** The mono micro-label used across the desk (`web/CLAUDE.md`: 10px, ls 1.5, uppercase,
 *  `--text-muted`). Declared once here because five panels use it. */
export const MONO_LABEL: React.CSSProperties = {
  fontFamily: "var(--font-mono), monospace",
  fontSize: 10,
  letterSpacing: 1.5,
  textTransform: "uppercase",
  color: "var(--text-muted)",
};

export const FRESHNESS_COLOR: Record<string, string> = {
  fresh: "var(--positive)",
  aging: "var(--warning)",
  stale: "var(--negative)",
};
