import type { Theme } from "./view";

import { Panel } from "./Panel";
import styles from "./flash.module.css";

/** continue / strengthen → up, fade / reverse → down, anything else neutral. */
function toneOf(token: string): "up" | "down" | "hold" {
  const t = token.toLowerCase();
  if (t === "strengthen" || t === "continue") return "up";
  if (t === "fade" || t === "reverse") return "down";
  return "hold";
}

/**
 * The standing themes, each with the condition that would end it.
 *
 * The kill line is the point of the block: a theme without a stated exit is an
 * opinion that can never be wrong. `killMet` is helium's verdict, so the row
 * says KILL MET rather than argon re-testing the condition it did not measure.
 * The excess figures are printed as the run wrote them — sign, unit and all.
 */
export function ThemesPanel({ themes }: { themes: Theme[] }) {
  return (
    <Panel title="Themes" tail={`${themes.length} standing`}>
      {themes.map((t, i) => (
        <div
          key={`${t.id}-${i}`}
          style={{
            padding: "10px 0",
            borderBottom:
              i === themes.length - 1
                ? undefined
                : "1px solid rgba(30, 41, 59, .55)",
          }}
        >
          <div
            style={{
              display: "flex",
              gap: 10,
              alignItems: "baseline",
              marginBottom: 5,
            }}
          >
            <span
              className={styles.mono}
              style={{ fontSize: 12, fontWeight: 700 }}
            >
              {t.id}
            </span>
            {t.token ? (
              <span className={styles.state} data-state={toneOf(t.token)}>
                {t.token}
              </span>
            ) : null}
            <div className={styles.lvls}>
              <div>
                <span className={styles.lbl}>1w excess</span>
                <span className={styles.mono}>{t.excess1w ?? "—"}</span>
              </div>
              <div>
                <span className={styles.lbl}>since entered</span>
                <span className={styles.mono}>
                  {t.excessSinceEntered ?? "—"}
                </span>
              </div>
            </div>
          </div>
          {t.leadership ? (
            <div className={styles.lbl} style={{ marginBottom: 4 }}>
              leadership {t.leadership}
            </div>
          ) : null}
          {t.why ? (
            <p
              className={styles.bodyText}
              style={{ margin: "0 0 5px", fontSize: 12.5 }}
            >
              {t.why}
            </p>
          ) : null}
          {t.kill ? (
            <p
              style={{
                margin: 0,
                fontSize: 11.5,
                lineHeight: 1.5,
                color: t.killMet ? "var(--negative)" : "var(--text-muted)",
              }}
            >
              <span className={styles.lbl}>
                {t.killMet ? "kill met" : "kill"}
              </span>{" "}
              {t.kill}
            </p>
          ) : null}
        </div>
      ))}
    </Panel>
  );
}
