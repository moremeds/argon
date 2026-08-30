import { OverviewDesk } from "@/components/macro/OverviewDesk";
import {
  DELTA_SERIES,
  type DeltaSeries,
  type DomainWeek,
} from "@/components/macro/overview/zone1";
import { replayVerdictForDomainState } from "@/components/macro/replay";
import type { MacroTabProps } from "@/components/macro/tabs";
import type {
  MacroContextSnapshot,
  MacroDomainKey,
  MacroDomainState,
  MacroOverviewSlot,
} from "@/components/macro/types";
import { settle } from "@/components/rates/deskShared";
import { api } from "@/lib/api";

/**
 * Tab 00 — Overview · Daily Loop.
 *
 * FIVE publishers, the only tab on the desk with more than three, and the reason is
 * structural: it is the tab whose subject is the other tabs. `/api/macro/snapshot` for the
 * chain verdict, plus one call per domain for the four answers it is a verdict about.
 *
 * ONE CALL PER DOMAIN rather than a bundle, carried from the `/macro` page this replaces:
 * the four engines run on separate schedules and any of them can be absent, so a bundling
 * endpoint would make one missing state look like a failed page — and saying which half is
 * missing is the whole job. `api.macroDomainState` allows a 404 through as `null`, which
 * is a fact to render, not an error to throw.
 *
 * THE SNAPSHOT IS FETCHED BESIDE THE FOUR, NEVER INSTEAD OF THEM (§9 invariant 8). It
 * answers the one question none of them can — whether they belong together — and its own
 * failure renders as an unreachable-chain notice, never as a clean chain.
 *
 * REPLAY: all five take the same `as_of` date and all five carry an answer clock. The
 * verdict is driven by each response's `as_of` (the instant the stored answer answers for)
 * and NOT by `computed_at`, because these routes select `WHERE as_of <= %s` and tie-break
 * on the LATER `computed_at` — `storage/macro_domain_state.py:216-219` states that a later
 * recompute of the same instant is legitimate, so a `computed_at` check would withhold a
 * state the contract permits. `as_of` is the request's own bound echoed back, so the check
 * fails exactly when the API did not apply the parameter, which is what it is for.
 */
export async function OverviewTab({ replay }: MacroTabProps) {
  const asOf = replay.kind === "replay" ? replay.asOf : undefined;

  /**
   * The board's zone 1 compares the desk against ITSELF a week earlier, and there is no
   * state-history endpoint to read that from. Point-in-time replay is what makes it
   * possible: the same four routes, asked twice, at two instants.
   *
   * The window is anchored on the REQUESTED instant when replaying and on today when not,
   * so a replay of 2026-08-20 compares against 08-13 rather than against last week of
   * wall-clock time. Anchoring on `Date.now()` in both cases would silently make every
   * replayed zone-1 a comparison between the replayed instant and the present.
   */
  const anchor = asOf ? new Date(`${asOf}T00:00:00Z`) : new Date();
  const priorDate = new Date(anchor.getTime() - WEEK_MS);
  const priorAsOf = priorDate.toISOString().slice(0, 10);
  const priorLabel = priorAsOf.slice(5);
  const nowLabel = anchor.toISOString().slice(5, 10);

  const [
    inflation,
    rates,
    usd,
    gold,
    snapshot,
    policy,
    gauge,
    priorInflation,
    priorRates,
    priorUsd,
    priorGold,
    ...deltaResults
  ] = await Promise.all([
    settle(
      () => api.macroDomainState("inflation", asOf),
      "inflation state API",
    ),
    settle(() => api.macroDomainState("rates", asOf), "policy/rates state API"),
    settle(() => api.macroDomainState("usd", asOf), "USD state API"),
    settle(() => api.macroDomainState("gold", asOf), "gold state API"),
    settle(() => api.macroContextSnapshot(asOf), "macro context snapshot API"),
    settle(() => api.macroPolicy(asOf), "macro policy comparison API"),
    settle(() => api.goldGauge(asOf), "gold gauge API"),
    // The prior-instant reads. These deliberately carry NO replay verdict: they are
    // evidence inside one panel, not a publisher the tab stands on, and giving them a
    // verdict would let a missing week-ago state withhold the whole tab.
    settle(
      () => api.macroDomainState("inflation", priorAsOf),
      "inflation state API (prior week)",
    ),
    settle(
      () => api.macroDomainState("rates", priorAsOf),
      "policy/rates state API (prior week)",
    ),
    settle(
      () => api.macroDomainState("usd", priorAsOf),
      "USD state API (prior week)",
    ),
    settle(
      () => api.macroDomainState("gold", priorAsOf),
      "gold state API (prior week)",
    ),
    ...DELTA_SERIES.map((spec) =>
      settle(
        () =>
          api.goldInputSeries(spec.id, {
            from: priorAsOf,
            to: anchor.toISOString().slice(0, 10),
            asOf,
          }),
        `${spec.id} series API`,
      ),
    ),
  ]);

  const deltas: DeltaSeries[] = DELTA_SERIES.map((spec, i) => ({
    spec,
    points: deltaResults[i]?.value?.points ?? [],
    error: deltaResults[i]?.error,
  }));

  // The API applies the replay instant to both source vintages and persisted gauge rows.
  // Keep the presentation boundary too: it protects a mixed-image deploy and makes an
  // old API response without `history_60d` settle to honest empty coverage, not a crash.
  const gaugeAtInstant = {
    value: gauge.value
      ? {
          history_60d: (gauge.value.history_60d ?? []).filter(
            (point) => asOf === undefined || point.obs_date <= asOf,
          ),
        }
      : null,
    error: gauge.error,
  };

  /** One settled fetch plus what it answered for. `as_of` is the clock — see above. */
  /**
   * One settled fetch plus the verdict on what it answered for.
   *
   * `replayVerdictForDomainState`, not `replayVerdict`, and the two instants are kept
   * APART. This tab was written on a branch where `ReplayStatus` took an `answerClock`
   * and this helper passed `as_of` in the field named `computedAt` to select the
   * "answers for" wording. That prop is gone; `ReplayStatus` now says "That answer was
   * computed …" for every instant tab, and feeding it an `as_of` under that sentence
   * would print one instant under the other's name.
   *
   * So the gate reads `as_of` — the instant the stored answer answers for, which is what
   * `/api/macro/*` selects on — and the sentence reads the real `computed_at`. Both are
   * then true. A state legitimately recomputed after the instant it answers for is still
   * shown, which is the behaviour `storage/macro_domain_state.py:216-219` requires.
   *
   * The snapshot's build instant is `assembled_at`, not `computed_at`; it is passed in by
   * the caller rather than guessed here, so a shape without one cannot silently report
   * `undefined` as its provenance.
   */
  const withVerdict = <T extends { as_of: string }>(
    settled: { value: T | null; error?: string },
    computedAt?: (value: T) => string | undefined,
  ): MacroOverviewSlot<T> => ({
    value: settled.value,
    error: settled.error,
    verdict: replayVerdictForDomainState(replay, {
      asOf: settled.value?.as_of,
      computedAt: settled.value ? computedAt?.(settled.value) : undefined,
      failed: Boolean(settled.error),
    }),
  });

  const domains: Record<MacroDomainKey, MacroOverviewSlot<MacroDomainState>> = {
    inflation: withVerdict(inflation, (v) => v.computed_at),
    // The API path segment is `rates`; the domain key the store and the causal order use
    // is `policy_rates`. Mapped here rather than anywhere downstream, so exactly one place
    // knows the two vocabularies differ.
    policy_rates: withVerdict(rates, (v) => v.computed_at),
    usd: withVerdict(usd, (v) => v.computed_at),
    gold: withVerdict(gold, (v) => v.computed_at),
  };

  const week: DomainWeek = {
    inflation: { now: domains.inflation, prior: priorInflation },
    policy_rates: { now: domains.policy_rates, prior: priorRates },
    usd: { now: domains.usd, prior: priorUsd },
    gold: { now: domains.gold, prior: priorGold },
  };

  return (
    <OverviewDesk
      domains={domains}
      week={week}
      snapshot={withVerdict<MacroContextSnapshot>(
        snapshot,
        (v) => v.assembled_at,
      )}
      policy={policy}
      deltas={deltas}
      gauge={gaugeAtInstant}
      priorLabel={priorLabel}
      nowLabel={nowLabel}
      windowLabel="1 week"
    />
  );
}

/** The zone-1 comparison window. One week, as the board's own zone kicker states. */
const WEEK_MS = 7 * 24 * 60 * 60 * 1000;
