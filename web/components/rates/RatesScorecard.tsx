"use client";

import { ChevronDown, ChevronRight } from "lucide-react";
import { useMemo, useState } from "react";
import type { components } from "@/lib/types";
import styles from "./RatesDesk.module.css";
import { fmtSigned, toFiniteNumber } from "./format";

type Scorecard = components["schemas"]["RatesScorecard"];

function stance(score: number): string {
  if (score >= 0.5) return "BUY duration";
  if (score <= -0.5) return "SELL duration";
  return "NEUTRAL duration";
}

export function RatesScorecard({ scorecard }: { scorecard: Scorecard }) {
  const groups = useMemo(() => scorecard.groups ?? [], [scorecard.groups]);
  const [open, setOpen] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(groups.map((group) => [group.id, true])),
  );

  const composite = useMemo(() => {
    if (scorecard.composite_score != null) {
      return toFiniteNumber(scorecard.composite_score, 0);
    }
    let weighted = 0;
    let total = 0;
    for (const group of groups) {
      if (group.status === "missing") continue;
      const weight = Math.max(0, toFiniteNumber(group.weight));
      const score = toFiniteNumber(group.score, 0);
      weighted += weight * score;
      total += weight;
    }
    return total > 0 ? weighted / total : 0;
  }, [groups, scorecard.composite_score]);

  return (
    <div className={styles.scorecard}>
      <div className={styles.scoreHero}>
        <div>
          <p className={styles.eyebrow}>Duration Composite</p>
          <strong data-testid="duration-score">{fmtSigned(composite, "", 2)}</strong>
        </div>
        <span className={styles.stance}>{stance(composite)}</span>
        <span className={styles.stance}>Curve {scorecard.curve_stance}</span>
      </div>

      <div className={styles.scoreGroups}>
        {groups.map((group) => {
          const isOpen = open[group.id] ?? true;
          return (
            <article key={group.id} className={styles.scoreGroup}>
              <div className={styles.scoreGroupTop}>
                <button
                  type="button"
                  className={styles.iconTitleButton}
                  onClick={() =>
                    setOpen((prev) => ({ ...prev, [group.id]: !isOpen }))
                  }
                >
                  {isOpen ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                  {group.label}
                </button>
                <span className={styles.staticWeight}>
                  Weight {toFiniteNumber(group.weight).toFixed(2)}
                </span>
                <span className={styles.groupScore}>{fmtSigned(group.score, "", 2)}</span>
              </div>
              {isOpen ? (
                <div className={styles.factorList}>
                  {(group.factors ?? []).map((factor) => (
                    <div key={factor.label} className={styles.factorRow}>
                      <span>{factor.label}</span>
                      <span>{factor.value ?? "Unavailable"}</span>
                      <strong>{fmtSigned(factor.score, "", 1)}</strong>
                    </div>
                  ))}
                </div>
              ) : null}
            </article>
          );
        })}
      </div>
    </div>
  );
}
