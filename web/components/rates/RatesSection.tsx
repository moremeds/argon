import styles from "./RatesDesk.module.css";

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
