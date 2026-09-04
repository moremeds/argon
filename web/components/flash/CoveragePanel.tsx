import { Panel } from "./Panel";
import type { Section } from "./view";
import styles from "./flash.module.css";

/**
 * The coverage body is printed as the run wrote it, `pre-wrap`.
 *
 * DO NOT PARSE IT INTO A TABLE. Its shape belongs to the tenant, and a parser
 * here breaks silently the first time that shape changes — showing a tidy,
 * wrong table instead of the text that was actually recorded.
 */
export function CoveragePanel({ coverage }: { coverage: Section }) {
  return (
    <Panel title={coverage.title || "Data coverage"}>
      <p className={styles.pre} style={{ fontSize: 11.5, lineHeight: 1.6 }}>
        {coverage.body}
      </p>
    </Panel>
  );
}
