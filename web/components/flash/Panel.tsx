import type { ReactNode } from "react";

import styles from "./flash.module.css";

/**
 * The only container on the page. Everything that is not a tile, a lead or a
 * card sits inside one of these, so the page reads as a single grid rather
 * than a collection of one-off boxes.
 */
export function Panel({
  title,
  tail,
  children,
  bodyClassName,
}: {
  title: string;
  tail?: string;
  children: ReactNode;
  bodyClassName?: string;
}) {
  return (
    <section className={styles.panel}>
      <h3>
        {title}
        {tail ? <span className={styles.tail}>{tail}</span> : null}
      </h3>
      <div className={bodyClassName ?? styles.pbody}>{children}</div>
    </section>
  );
}
