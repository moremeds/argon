import styles from "./RatesDesk.module.css";

/**
 * A band heading that groups the sections under it.
 *
 * The desk used to be fifteen sections at one visual weight behind a flat
 * fifteen-item nav, which is a list, not a hierarchy -- the verdict, the publishers
 * who feed it, the market's own pricing and the legacy scorecard all shouted equally
 * and the reader had to know the page to find anything. Tiers answer "what am I
 * looking at" before "which panel".
 */
export function RatesTier({
  id,
  title,
  lede,
}: {
  id: string;
  title: string;
  lede: string;
}) {
  return (
    <div className={styles.tier} id={id} data-testid={`rates-tier-${id}`}>
      <h2 className={styles.tierTitle}>{title}</h2>
      <p className={styles.tierLede}>{lede}</p>
    </div>
  );
}

export function RatesSection({
  id,
  title,
  eyebrow,
  status,
  children,
}: {
  id: string;
  title: string;
  eyebrow?: string;
  status?: string;
  children: React.ReactNode;
}) {
  return (
    <section id={id} className={styles.section} aria-labelledby={`${id}-title`}>
      <div className={styles.sectionHeader}>
        <div>
          {eyebrow ? <p className={styles.eyebrow}>{eyebrow}</p> : null}
          <h2 id={`${id}-title`}>{title}</h2>
        </div>
        {status ? <span className={styles.statusPill}>{status}</span> : null}
      </div>
      {children}
    </section>
  );
}
