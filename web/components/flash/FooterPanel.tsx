import type { BriefFooter } from "./view";

import { Panel } from "./Panel";
import styles from "./flash.module.css";

function List({ label, items }: { label: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <div style={{ marginBottom: 10 }}>
      <div className={styles.lbl} style={{ marginBottom: 4 }}>
        {label}
      </div>
      <ul
        className={styles.mono}
        style={{
          margin: 0,
          paddingLeft: 16,
          fontSize: 11,
          lineHeight: 1.7,
          color: "var(--text-muted)",
          wordBreak: "break-word",
        }}
      >
        {items.map((item, i) => (
          <li key={i}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

/**
 * Which layer came from which source, when each was read, and what qualifies
 * it. Printed verbatim: an as-of line rewritten into argon's own format is a
 * provenance claim argon did not make.
 */
export function FooterPanel({
  footer,
  staleness,
}: {
  footer: BriefFooter;
  staleness?: string[];
}) {
  const stale = staleness ?? [];
  return (
    <Panel title="Sources & as-of" tail="this run">
      <List label="coverage" items={footer.coverage ?? []} />
      <List label="as of" items={footer.asOf ?? []} />
      <List label="notes" items={footer.notes ?? []} />
      <List label="stale inputs" items={stale} />
    </Panel>
  );
}
