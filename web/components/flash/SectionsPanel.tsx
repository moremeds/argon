import { Body } from "./Body";
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
  tickers,
}: {
  title: string;
  tail?: string;
  sections: Section[];
  scroll?: boolean;
  pre?: boolean;
  tickers?: ReadonlySet<string>;
}) {
  const body = (
    <div className={styles.secgrid}>
      {sections.map((s, i) => (
        <article key={`${s.title}-${i}`} className={styles.seccard}>
          <h4>{s.title}</h4>
          {pre ? (
            <p className={styles.pre}>{s.body}</p>
          ) : (
            <Body text={s.body} tickers={tickers} />
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
