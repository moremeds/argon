import { Panel } from "./Panel";
import type { Section } from "./view";
import styles from "./flash.module.css";

/** The run's prose, headings and all, in the order it wrote them. */
export function SectionsPanel({
  title,
  tail,
  sections,
  scroll,
  pre,
}: {
  title: string;
  tail?: string;
  sections: Section[];
  scroll?: boolean;
  pre?: boolean;
}) {
  const body = (
    <div className={styles.stack}>
      {sections.map((s, i) => (
        <div key={`${s.title}-${i}`}>
          <h4
            style={{
              margin: "0 0 4px",
              fontSize: 12.5,
              fontWeight: 700,
              color: "var(--text-primary)",
            }}
          >
            {s.title}
          </h4>
          {pre ? (
            <p className={styles.pre}>{s.body}</p>
          ) : (
            <p
              style={{
                margin: 0,
                fontSize: 12.5,
                lineHeight: 1.6,
                color: "var(--text-secondary)",
                maxWidth: "110ch",
              }}
            >
              {s.body}
            </p>
          )}
        </div>
      ))}
    </div>
  );
  return (
    <Panel title={title} tail={tail}>
      {scroll ? <div className={styles.scroll}>{body}</div> : body}
    </Panel>
  );
}
