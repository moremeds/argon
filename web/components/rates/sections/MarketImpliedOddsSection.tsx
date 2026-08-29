import styles from "../RatesDesk.module.css";
import { fmtValue } from "../format";
import type { PolicyPathSlot } from "../types";

/**
 * Board t1 — "Per-meeting odds · market-implied" (Q2, Q6).
 *
 * ### Why this panel exists when the data does not
 *
 * `/api/macro/policy` returns `market_implied` as a THREE-STATE slot, and today it is in
 * its third state: `path` is null and `missing_reason` reads "no PIT-eligible market
 * implied policy release". The board still gives it a panel, and shipping without one was
 * the difference between two claims the desk must never confuse:
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
      <div className={`${styles.notePanel} ${styles.noteRefuse}`}>
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
    <div className={styles.supplyTableWrap}>
      <table className={styles.supplyTable}>
        <thead>
          <tr>
            <th>Meeting</th>
            <th>Implied rate</th>
            {/* The board's panel is "per-meeting ODDS", and the odds live in each
                point's `probability_distribution`. A point that carries none prints the
                implied rate alone rather than an empty column, because a meeting the
                publisher priced without a distribution is not a meeting it skipped. */}
            <th>Distribution</th>
          </tr>
        </thead>
        <tbody>
          {points.map((point) => (
            <tr key={point.horizon}>
              <td>
                <strong>{point.horizon}</strong>
                {point.horizon_date && <small>{point.horizon_date}</small>}
              </td>
              <td>{fmtValue(point.rate_percent, "%", 2)}</td>
              <td>
                {(point.probability_distribution ?? []).length === 0
                  ? "—"
                  : (point.probability_distribution ?? [])
                      .map(
                        (bucket) =>
                          `${bucket.label} ${fmtValue(
                            bucket.probability_percent,
                            "%",
                            0,
                          )}`,
                      )
                      .join(" · ")}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {slot.path?.release_date && (
        <p className={styles.positioningRead}>
          Released {slot.path.release_date} by{" "}
          {slot.path.source ?? "an unnamed publisher"}. Each release is read
          against its own date — an older one says nothing about the weeks
          since.
        </p>
      )}
    </div>
  );
}
