"use client";

import { ChevronDown, ChevronRight } from "lucide-react";
import { useMemo, useState } from "react";
import type { components } from "@/lib/types";
import styles from "./RatesDesk.module.css";
import { fmtSigned, toFiniteNumber } from "./format";

type Scorecard = components["schemas"]["RatesScorecard"];

// The composite is the server's, or it does not exist.
//
// This component used to renormalise the weights itself and fall back to 0 when every
// group was missing, which then rendered as "NEUTRAL duration" -- a confident verdict
// manufactured out of nothing. The server already decides both the composite and
// whether coverage is high enough to take a stance, so the client's job is to print
// what it decided, including the refusal.

function fmtComposite(score: number | null): string {
  return score == null ? "n/a" : fmtSigned(score, "", 2);
}

function fmtCoverage(coverage: number | null | undefined): string | null {
  const n = toFiniteNumber(coverage, Number.NaN);
  if (!Number.isFinite(n)) return null;
  return `${(n * 100).toFixed(0)}% of weight scored`;
}

export function RatesScorecard({ scorecard }: { scorecard: Scorecard }) {
  const groups = useMemo(() => scorecard.groups ?? [], [scorecard.groups]);
  const [open, setOpen] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(groups.map((group) => [group.id, true])),
  );

  const composite =
    scorecard.composite_score == null
      ? null
      : toFiniteNumber(scorecard.composite_score, Number.NaN);
  const coverage = fmtCoverage(scorecard.coverage);

  return (
    <div className={styles.scorecard} data-testid="rates-scorecard">
      {/* Dual-read: this rule score predates the state engine and is kept only so its
          history stays readable. It is not the contract the desk answers with. */}
      <p className={styles.legacyBanner} data-testid="scorecard-legacy-banner">
        Experimental legacy · superseded by the policy / rates state above. Kept
        visible during dual-read; not a decision surface.
      </p>

      <div className={styles.scoreHero}>
        <div>
          <p className={styles.eyebrow}>Duration Composite</p>
          <strong data-testid="duration-score">
            {fmtComposite(composite)}
          </strong>
        </div>
        <span className={styles.stance} data-testid="duration-stance">
          {scorecard.duration_stance} duration
        </span>
        <span className={styles.stance}>Curve {scorecard.curve_stance}</span>
      </div>

      {composite == null || scorecard.duration_stance === "UNKNOWN" ? (
        <p className={styles.stateEmptyNote} data-testid="scorecard-no-score">
          {scorecard.coverage_detail ??
            "Not enough scored groups to compute a composite."}{" "}
          No duration stance is taken.
        </p>
      ) : coverage ? (
        <p className={styles.stateEmptyNote}>{coverage}</p>
      ) : null}

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
                  {isOpen ? (
                    <ChevronDown size={16} />
                  ) : (
                    <ChevronRight size={16} />
                  )}
                  {group.label}
                </button>
                <span className={styles.staticWeight}>
                  Weight {toFiniteNumber(group.weight).toFixed(2)}
                </span>
                <span className={styles.groupScore}>
                  {group.status === "missing"
                    ? "unscored"
                    : fmtSigned(group.score, "", 2)}
                </span>
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
