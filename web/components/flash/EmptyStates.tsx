import type { ReactNode } from "react";

import { FLASH_TENANT } from "@/lib/flash/kinds";

import { Panel } from "./Panel";
import styles from "./flash.module.css";

/**
 * The empty states carry the audit line on purpose.
 *
 * "Nothing here" and "we looked and found nothing" are different claims, and
 * only the second one is checkable. Every empty state below names the tenant,
 * the phase and the date it queried, so a reader can go ask helium the same
 * question and get the same answer.
 */

export function NoWeeksYet({ reason }: { reason: "api" | "empty" }) {
  return (
    <div className={styles.empty}>
      <span className={styles.big}>
        {reason === "api" ? "Agent-run API unreachable" : "No runs recorded"}
      </span>
      <p>
        {reason === "api"
          ? "Argon could not reach the agent-run API, so it cannot say whether a flash exists. This is an argon-side fault, not an empty week."
          : "No option-wizard run has been recorded yet. The first one appears here the morning helium's delivery channel posts it."}
      </p>
      <span className={styles.provenance}>
        helium audit — 0 weeks for tenant {FLASH_TENANT}
      </span>
    </div>
  );
}

export function NoRunRecorded({
  day,
  kind,
  isFuture,
}: {
  day: string;
  kind: string;
  isFuture: boolean;
}) {
  return (
    <>
      <div className={styles.empty}>
        <span className={styles.big}>No run recorded</span>
        <p>
          {isFuture
            ? `The option-wizard ${kind} run for ${day} has not been recorded yet. The layout below is the empty shell, not a rendered flash.`
            : `No option-wizard ${kind} run was recorded for ${day}. The layout below is the empty shell, not a rendered flash.`}
        </p>
        <span className={styles.provenance}>
          helium audit — 0 runs for tenant {FLASH_TENANT}, phase {kind}, date{" "}
          {day}
        </span>
      </div>
      <PremarketSkeleton />
    </>
  );
}

const RAIL_PANELS = [
  "Overnight",
  "Today's schedule",
  "Rates & policy path",
  "Gamma profile",
  "Risk register",
  "Data coverage",
];

/**
 * The shape of the page that is missing, at 42% opacity.
 *
 * It is `aria-hidden` because a screen reader reading nine empty tiles would
 * be reading furniture; the sighted reader gets the same information from the
 * silhouette, which is what a skeleton is for.
 */
export function PremarketSkeleton() {
  return (
    <div className={styles.skel} aria-hidden="true">
      <div
        className={styles.tape}
        style={{ gridTemplateColumns: "repeat(9, minmax(0, 1fr))" }}
      >
        {Array.from({ length: 9 }, (_, i) => (
          <div key={i} className={styles.tile}>
            <span className={styles.ghost} style={{ width: "40%" }} />
            <span className={styles.ghost} style={{ height: 18 }} />
            <span className={styles.ghost} style={{ width: "55%" }} />
          </div>
        ))}
      </div>
      <div className={styles.lead} style={{ marginTop: 12 }}>
        <span className={styles.ghost} style={{ width: 70 }} />
        <span className={styles.ghost} style={{ flex: 1 }} />
      </div>
      <div className={styles.cols}>
        <div className={styles.colL}>
          <div className={styles.ghostbox} style={{ height: 220 }} />
          <div className={styles.ghostbox} style={{ height: 160 }} />
        </div>
        <div className={styles.colR}>
          {RAIL_PANELS.map((title) => (
            <Panel key={title} title={title}>
              <div className={styles.ghostbox} style={{ height: 56 }} />
            </Panel>
          ))}
        </div>
      </div>
    </div>
  );
}

/** The amber band: something the run said it could not do. Never a colour alone. */
export function PlaceholderBand({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div className={styles.band}>
      <span className={`${styles.lbl} ${styles.bandLabel}`}>{label}</span>
      <p>{children}</p>
    </div>
  );
}
