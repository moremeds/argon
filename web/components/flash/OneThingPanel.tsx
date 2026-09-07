import type { Check, ChangeMyMind, OneThing } from "./view";

import { Body } from "./Body";
import { Panel } from "./Panel";
import styles from "./flash.module.css";

/**
 * The three checks the claim will be scored against tomorrow.
 *
 * Each one names a series, the level it sits at now, and the question that
 * settles it — a claim with no stated check cannot be wrong, which is the
 * failure this block exists to prevent.
 *
 * There is deliberately NO hit / miss / not-observed pill: no stored run
 * carries a per-check verdict field. helium scores yesterday's checks in one
 * sentence (`oneThing.checksLine`), which is printed above, and inventing a
 * per-row state here would be argon scoring a check it never observed.
 */
export function ChecksList({ checks }: { checks: Check[] }) {
  return (
    <ol className={styles.checks}>
      {checks.map((c, i) => (
        <li key={i}>
          <div className={styles.checkHead}>
            <span className={styles.mono} style={{ fontWeight: 700 }}>
              {c.series ?? "—"}
            </span>
            {c.level ? (
              <span className={`${styles.mono} ${styles.checkLevel}`}>
                at {c.level}
              </span>
            ) : null}
          </div>
          <span className={styles.checkText}>{c.text}</span>
        </li>
      ))}
    </ol>
  );
}

/**
 * The day's single claim, what would settle it, and what would break it.
 *
 * Order is the argument: the claim, then why it is the claim, then the checks
 * that can falsify it, then the condition under which the run would drop it.
 * Nothing below this panel outranks it.
 */
export function OneThingPanel({
  oneThing,
  checks,
  changeMyMind,
  tickers,
}: {
  oneThing?: OneThing;
  checks?: Check[];
  changeMyMind?: ChangeMyMind;
  tickers?: ReadonlySet<string>;
}) {
  if (!oneThing && !(checks && checks.length > 0) && !changeMyMind) return null;

  // helium sometimes opens the body with the same scoring sentence it puts in
  // `checksLine`. Printing both makes the run look like it scored yesterday
  // twice, so the standalone line is dropped when the body already carries it.
  const checksLine =
    oneThing?.checksLine && !oneThing.body?.includes(oneThing.checksLine)
      ? oneThing.checksLine
      : null;

  return (
    <Panel
      title={oneThing?.title || "The one thing"}
      tail={oneThing?.why || undefined}
    >
      {oneThing?.body ? <Body text={oneThing.body} tickers={tickers} /> : null}

      {checksLine ? (
        <p
          style={{
            margin: "10px 0 0",
            fontSize: 11.5,
            color: "var(--text-muted)",
          }}
        >
          {checksLine}
        </p>
      ) : null}

      {checks && checks.length > 0 ? (
        <>
          <div className={styles.lbl} style={{ margin: "12px 0 6px" }}>
            checks · settle tomorrow
          </div>
          <ChecksList checks={checks} />
        </>
      ) : null}

      {changeMyMind ? (
        <div className={styles.cmm}>
          <div className={styles.lbl} style={{ marginBottom: 4 }}>
            change my mind
          </div>
          <p style={{ margin: 0 }}>{changeMyMind.text}</p>
          {changeMyMind.series ||
          changeMyMind.threshold ||
          changeMyMind.horizon ? (
            <div className={styles.cmmMeta}>
              {[
                changeMyMind.series,
                changeMyMind.threshold,
                changeMyMind.horizon,
              ]
                .filter(Boolean)
                .join(" · ")}
            </div>
          ) : null}
        </div>
      ) : null}
    </Panel>
  );
}
