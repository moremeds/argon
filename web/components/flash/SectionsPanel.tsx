import { Body } from "./Body";
import { Panel } from "./Panel";
import type { Section } from "./view";
import styles from "./flash.module.css";

/**
 * A body past this many characters is an essay, not a note, and reads badly in
 * a 340px column — it takes two. The threshold is a layout judgement, not a
 * claim about the section.
 */
const WIDE_BODY = 900;

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
    <div className={styles.secgrid}>
      {sections.map((s, i) => (
        <article
          key={`${s.title}-${i}`}
          className={`${styles.seccard}${
            (s.body?.length ?? 0) > WIDE_BODY ? ` ${styles.secwide}` : ""
          }`}
        >
          <h4>{s.title}</h4>
          {pre ? (
            <p className={styles.pre}>{s.body}</p>
          ) : (
            <Body text={s.body} />
          )}
        </article>
      ))}
    </div>
  );
  return (
    <Panel title={title} tail={tail}>
      {scroll ? <div className={styles.scroll}>{body}</div> : body}
    </Panel>
  );
}
