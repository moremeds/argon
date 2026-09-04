import { GammaBars } from "./GammaBars";
import { Panel } from "./Panel";
import type { GammaProfile } from "./view";
import styles from "./flash.module.css";

export function GammaProfilePanel({ profiles }: { profiles: GammaProfile[] }) {
  return (
    <Panel title="Gamma profile" tail="dealer gamma per strike">
      {profiles.map((p) => (
        <div key={p.ticker} className={styles.gx}>
          <div className={styles.gxh}>
            <span
              className={styles.mono}
              style={{ fontSize: 13, fontWeight: 700 }}
            >
              {p.ticker}
            </span>
            {p.spot != null ? (
              <span
                className={styles.mono}
                style={{ fontSize: 10, color: "var(--text-muted)" }}
              >
                Spot {p.spot}
              </span>
            ) : null}
          </div>
          <GammaBars ticker={p.ticker} spot={p.spot} levels={p.levels} />
        </div>
      ))}
      <p
        style={{
          margin: "12px 0 0",
          fontSize: 11,
          lineHeight: 1.5,
          color: "var(--text-muted)",
        }}
      >
        A bar is its size, its side of the axis the sign. Left of zero is
        negative gamma, where hedging amplifies rather than damps. Duplicate
        strike rows are collapsed.
      </p>
    </Panel>
  );
}
