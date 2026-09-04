import styles from "./flash.module.css";

/**
 * The one sentence the run leads with. Two lines of mono label on the left so
 * the eye lands on the sentence, not on the frame.
 */
export function Lead({
  label,
  text,
  size = "lead",
}: {
  label: [string, string];
  text: string;
  size?: "lead" | "supplement";
}) {
  return (
    <div className={styles.lead} data-size={size}>
      <span className={`${styles.lbl} ${styles.leadLabel}`}>
        {label[0]}
        <br />
        {label[1]}
      </span>
      <p>{text}</p>
    </div>
  );
}
