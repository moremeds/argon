import { BoardRead } from "@/components/macro/domain/BoardPanel";
import { MarketImpliedMeetingBars } from "@/components/macro/MarketImpliedMeetingBars";

import styles from "../RatesDesk.module.css";
import type { PolicyPathSlot } from "../types";

/**
 * Board t1 — "Per-meeting odds · market-implied" (Q2, Q6).
 *
 * ### Why this panel survives both available and unavailable publisher states
 *
 * `/api/macro/policy` returns `market_implied` as a THREE-STATE slot. A live Frenzy path
 * renders through the same meeting-bar component as Overview; a missing path remains a
 * named refusal. Keeping both branches prevents the desk from confusing two claims:
 *
 * - **absent panel** — "this desk does not cover market-implied odds"
 * - **panel with a refusal** — "this desk covers them, and the publisher had nothing"
 *
 * The first is false. The lane is one of the four the tab is built around, it has a named
 * source and a freshness record, and it is the one lane whose absence changes how the
 * other three should be read: without it there is nothing on the tab a market actually
 * traded, only what three bodies said.
 *
 * ### Why the freshness block is shown rather than summarised
 *
 * `releases_discovered: 0` and `consecutive_failures: 0` together say something specific
 * — nothing was found to fetch, as opposed to fetches that failed. A panel that printed
 * only "unavailable" would let a dead pipeline and an empty upstream look identical.
 */
export function MarketImpliedOddsSection({
  slot,
}: {
  slot: PolicyPathSlot | null | undefined;
}) {
  const points = slot?.path?.points ?? [];
  const freshness = slot?.freshness;

  if (!slot) {
    return (
      <div className={styles.notePanel}>
        <p>
          The policy comparison did not answer, so whether a market-implied path
          exists is unknown. This is a failure to reach the publisher, not a
          statement about it.
        </p>
      </div>
    );
  }

  if (points.length === 0) {
    return (
      <div className="note-refuse">
        <p>
          <strong>No market-implied path for this instant.</strong>{" "}
          {slot.missing_reason ??
            "The publisher returned no point-in-time eligible release."}
        </p>
        {freshness && (
          <p>
            Source <code>{freshness.source ?? "unknown"}</code> ·{" "}
            {freshness.releases_discovered ?? 0} releases discovered,{" "}
            {freshness.releases_succeeded ?? 0} succeeded,{" "}
            {freshness.releases_failed ?? 0} failed
            {typeof freshness.consecutive_failures === "number" &&
              ` · ${freshness.consecutive_failures} consecutive failures`}
            .{" "}
            {(freshness.releases_discovered ?? 0) === 0 &&
            (freshness.consecutive_failures ?? 0) === 0
              ? "Nothing was found to fetch — an empty upstream, not a broken pipeline."
              : "Fetches were attempted and did not land."}
          </p>
        )}
        <p>
          The other three lanes on this tab are what three bodies <em>said</em>.
          This is the only one that would be what a market <em>traded</em>, so
          its absence is worth stating rather than leaving as a gap between
          panels.
        </p>
      </div>
    );
  }

  return (
    <>
      <MarketImpliedMeetingBars points={points} />
      <BoardRead>
        Publisher probabilities by meeting; committee and dealer paths stay separate.
      </BoardRead>
      {slot.path?.release_date ? (
        <p className="cap">
          Released {slot.path.release_date} by{" "}
          {slot.path.source ?? "an unnamed publisher"}.
        </p>
      ) : null}
    </>
  );
}
