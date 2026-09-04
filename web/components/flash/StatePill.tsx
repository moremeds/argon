import styles from "./flash.module.css";

/**
 * The tenant's own word for what happened to a tracked structure.
 *
 * Argon classifies the word for colour and nothing else — it never rewrites
 * it, and an unrecognised word is rendered as written in the neutral tone
 * rather than dropped. A state argon does not know is still a state.
 */
function toneOf(state: string): "up" | "down" | "hold" {
  if (state.includes("加强")) return "up";
  if (state.includes("反转")) return "down";
  return "hold";
}

export function StatePill({ state }: { state: string }) {
  return (
    <span className={styles.state} data-state={toneOf(state)}>
      {state}
    </span>
  );
}
