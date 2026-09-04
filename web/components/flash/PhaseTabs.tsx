import Link from "next/link";

import type { AgentRunIndexRow } from "@/lib/api";
import { DAY_KINDS, KIND_LABEL, type DayKind } from "@/lib/flash/kinds";

import styles from "./flash.module.css";

/**
 * One tab per phase. A recorded phase is a Link; an absent one is a disabled
 * button — not a Link to a page that would only say "nothing here", and not a
 * hidden tab, because a phase that silently vanishes is indistinguishable from
 * a phase that was never scheduled.
 */
export function PhaseTabs({
  weekKey,
  day,
  runs,
  selected,
  asOf,
}: {
  weekKey: string;
  day: string;
  runs: AgentRunIndexRow[];
  selected: DayKind;
  asOf?: string;
}) {
  const recorded = new Set(
    runs.filter((r) => String(r.run_day) === day).map((r) => r.kind),
  );

  return (
    <div className={styles.phbar} role="tablist" aria-label="Flash phase">
      {DAY_KINDS.map((kind) => {
        const on = recorded.has(kind);
        const label = (
          <>
            <span className={styles.dot} data-on={String(on)} />
            {KIND_LABEL[kind]}
          </>
        );
        if (!on) {
          return (
            <button
              key={kind}
              type="button"
              role="tab"
              className={styles.ph}
              aria-selected={kind === selected}
              disabled
              title={`No ${kind} run recorded for ${day}.`}
            >
              {label}
            </button>
          );
        }
        return (
          <Link
            key={kind}
            role="tab"
            href={`/flash/${weekKey}/${day}?phase=${kind}`}
            className={styles.ph}
            aria-selected={kind === selected}
          >
            {label}
          </Link>
        );
      })}
      {asOf ? <span className={styles.asof}>as of {asOf}</span> : null}
    </div>
  );
}
