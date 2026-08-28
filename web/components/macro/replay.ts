/**
 * Point-in-time replay for the macro desk: what was ASKED, and what the store ANSWERED.
 *
 * The plan (`docs/superpowers/plans/2026-08-27-macro-desk-page-port.md` §3.1) names the
 * failure this module exists to prevent, and it is not "the date picker does not work":
 *
 *   > A replayed tab 01/03/04/05 beside a **live** tab 02, with nothing on screen saying
 *   > so, is the worst failure mode a point-in-time desk has.
 *
 * So the two halves are kept apart on purpose and never collapsed into one value:
 *
 *   - `MacroReplayRequest` is what the OPERATOR asked for. It comes off the URL, it is
 *     the same on every tab, and it survives tab switches (the bar carries `as_of`).
 *   - `ReplayVerdict` is what ONE publisher answered. It is per-tab, because each tab
 *     asks different publishers and any of them can decline separately.
 *
 * A banner driven by the request would say "replaying 2026-01-01" over whatever the API
 * happened to return. §8 of the plan measured why that is not hypothetical: a pre-P1
 * `argon-app` image answers `?as_of=2026-01-01` with the LIVE snapshot and a 200, because
 * FastAPI ignores a query parameter the route does not declare. The two images are pulled
 * independently by Watchtower with no ordering guarantee between them, so a web image
 * carrying this control can be live against an API image that cannot replay. The response
 * is the only thing that can tell the difference, which is why `replayVerdict` reads
 * `computed_at` and refuses rather than decorating.
 *
 * ### Three clocks, and this module speaks for exactly one of them
 *
 * §3.1 records three different meanings of "as of" among the surfaces tabs 01-05 bind:
 *
 *   | surface               | keys on                                        |
 *   | --------------------- | ---------------------------------------------- |
 *   | `/api/macro/*`        | an **instant** (`resolve_instant`)             |
 *   | `/api/rates/snapshot` | **`computed_at`** — when the answer existed    |
 *   | `/api/gold/replay`    | **`obs_date`** — the market day it is about    |
 *
 * The first two are the same question ("what did the desk know at T"); the third is a
 * different one ("what did the market do on day T"), matched with exact equality rather
 * than `<=`. §10-H settled it: **label it, do not change the API.** The label lives on
 * `MacroReplayClock`, which is a REQUIRED field of every tab registry entry, so tab 05
 * cannot inherit tab 02's question by leaving a field out.
 */

/**
 * Which question a tab's `as_of` control is asking. Required on every registry entry.
 *
 * - `instant`  — "as the desk stood at the end of this UTC day"; the answer is the
 *   newest one computed at or before that instant. Tabs 01/02 today; 00/03/04 later.
 * - `obs_date` — "the market day this reading is about", matched exactly. `/api/gold/replay`
 *   is `WHERE obs_date = %s` (`storage/gold.py:862-880`), so a day with no row has no
 *   answer and does not fall back to the day before. Tab 05, when P6 registers it.
 * - `none`     — the tab has no data path and no clock (tab 08, static prose).
 */
export type MacroReplayClock = "instant" | "obs_date" | "none";

/**
 * What the operator asked for, parsed from `?as_of=`.
 *
 * `rejected` is a third state on purpose. Silently treating garbage as `live` would hand
 * back today's desk to somebody who asked for a past date and say nothing — the same
 * class of lie as a replay banner over live data, pointed the other way.
 */
export type MacroReplayRequest =
  | { kind: "live" }
  | { kind: "replay"; asOf: string }
  | { kind: "rejected"; raw: string };

/**
 * What one publisher answered, once the request was a replay.
 *
 * The four replaying outcomes are §9 invariant 2's three states plus the deploy-race
 * refusal: answered (`replaying`) / request failed (`request_failed`) / never computed
 * (`unanswered`) / answered for the wrong instant (`answered_after`).
 */
export type ReplayVerdict =
  | { kind: "not_replaying" }
  | { kind: "replaying"; asOf: string; computedAt: string }
  | { kind: "unanswered"; asOf: string }
  | { kind: "request_failed"; asOf: string }
  /** `computedAt` is `null` when the response carried a timestamp we could not read —
   *  which is equally unshowable as that instant's answer, so it lands here. */
  | { kind: "answered_after"; asOf: string; computedAt: string | null };

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const DAY_MS = 86_400_000;
/** Enough characters to recognise what you typed, few enough that a pasted essay cannot
 *  become the page's largest element. (Phrased around the two obvious adjectives on
 *  purpose: both are banned vocabulary in `scripts/lint-gold-copy.mjs`, whose scope now
 *  covers this directory.) */
const MAX_ECHOED_RAW = 64;

/** `2026-02-30` matches the shape and is not a day. Round-tripping through `Date` is the
 *  cheapest way to ask the calendar rather than the regex. */
function isRealCalendarDay(value: string): boolean {
  const ms = Date.parse(`${value}T00:00:00Z`);
  if (Number.isNaN(ms)) return false;
  return new Date(ms).toISOString().slice(0, 10) === value;
}

/**
 * `?as_of=` -> what was asked.
 *
 * An absent or empty value is `live`: an empty value is what the control's own date input
 * submits when it has been cleared, and "I cleared the date" means "show me now".
 *
 * An ARRAY (`?as_of=a&as_of=b`) is rejected rather than resolved to one of them. Two
 * instants is two questions, and picking one silently answers a question nobody asked —
 * the same refusal `resolve_instant` makes when handed both `as_of` and `as_of_ts`
 * (`routers/macro.py:280-283`, HTTP 422).
 */
export function parseReplayRequest(
  raw: string | string[] | undefined,
): MacroReplayRequest {
  if (raw === undefined) return { kind: "live" };
  if (Array.isArray(raw)) {
    return { kind: "rejected", raw: raw.join(", ").slice(0, MAX_ECHOED_RAW) };
  }
  const trimmed = raw.trim();
  if (trimmed === "") return { kind: "live" };
  if (!DATE_RE.test(trimmed) || !isRealCalendarDay(trimmed)) {
    return { kind: "rejected", raw: raw.slice(0, MAX_ECHOED_RAW) };
  }
  return { kind: "replay", asOf: trimmed };
}

/**
 * An instant in milliseconds, treating a naive timestamp as UTC.
 *
 * This is not defensive padding. `RatesSnapshotResponse.computed_at` is a plain
 * `datetime` (`models/rates.py:241`), not an `AwareDatetime`, and the router defends
 * against exactly this — `if computed_at.tzinfo is None: computed_at.replace(tzinfo=UTC)`
 * (`routers/rates.py:99-100`). JavaScript does the OPPOSITE with the same string: per
 * ECMAScript, a date-time form with no offset is parsed as LOCAL time. On a UTC+8 desk
 * that moves the instant eight hours, which is enough to flip the day-boundary comparison
 * below and refuse a snapshot that was in fact computed in time. Normalising here keeps
 * the two sides of the wire agreeing about what a bare timestamp means.
 */
export function parseInstantMs(value: string): number | null {
  const normalized = /([zZ]|[+-]\d{2}:?\d{2})$/.test(value)
    ? value
    : `${value}Z`;
  const ms = Date.parse(normalized);
  return Number.isNaN(ms) ? null : ms;
}

/** The exclusive upper bound of a UTC day. `computed_at < this` is exactly the API's own
 *  `computed_at <= 23:59:59.999999` (`resolve_instant` uses `time.max`). */
function dayEndExclusiveMs(asOf: string): number {
  return Date.parse(`${asOf}T00:00:00Z`) + DAY_MS;
}

/** `2026-08-27` +/- n days, still as a UTC calendar date. */
export function shiftDay(asOf: string, days: number): string {
  return new Date(Date.parse(`${asOf}T00:00:00Z`) + days * DAY_MS)
    .toISOString()
    .slice(0, 10);
}

/** Today, in UTC, as `YYYY-MM-DD`. Called by the page and PASSED to the control, never
 *  read inside it — a component that reads the clock itself cannot be tested for what it
 *  renders on a boundary. */
export function todayUtcDate(): string {
  return new Date().toISOString().slice(0, 10);
}

/** `2026-08-27 03:42 UTC`. Always UTC: the whole comparison is against a UTC day
 *  boundary, so rendering the answer in a local zone would put the reader's arithmetic
 *  in a different frame from the desk's. */
export function formatInstantUtc(value: string): string {
  const ms = parseInstantMs(value);
  if (ms === null) return value;
  return `${new Date(ms).toISOString().slice(0, 16).replace("T", " ")} UTC`;
}

/** One tab's href with the replay date attached, or without it. */
export function replayHref(tabHref: string, asOf: string | null): string {
  return asOf ? `${tabHref}?as_of=${encodeURIComponent(asOf)}` : tabHref;
}

/**
 * What ONE publisher answered for the instant that was asked for.
 *
 * `answer.failed` is kept separate from a null `computedAt` because the desk keeps three
 * kinds of nothing apart (§9 invariant 2). "The request failed" and "no answer existed at
 * that instant" are different facts about different things — the first is about our API,
 * the second about the publisher's history — and collapsing them is the defect §4.6 of
 * the plan records `/gold`'s raw fetch shipping for months.
 */
export function replayVerdict(
  request: MacroReplayRequest,
  answer: { computedAt?: string | null; failed?: boolean },
): ReplayVerdict {
  if (request.kind !== "replay") return { kind: "not_replaying" };
  const { asOf } = request;
  if (answer.failed) return { kind: "request_failed", asOf };

  const computedAt = answer.computedAt ?? null;
  if (computedAt === null) return { kind: "unanswered", asOf };

  const ms = parseInstantMs(computedAt);
  if (ms === null) return { kind: "answered_after", asOf, computedAt: null };
  return ms < dayEndExclusiveMs(asOf)
    ? { kind: "replaying", asOf, computedAt }
    : { kind: "answered_after", asOf, computedAt };
}

/**
 * What ONE `/api/macro/{domain}` publisher answered — gated on `as_of`, not `computed_at`.
 *
 * This exists because `replayVerdict` above encodes the RATES contract, and the two
 * endpoint families do not key on the same column. §3.1 of the port plan groups them as
 * one clock ("what did the desk know at T") and for the operator they are; one level
 * down they are not:
 *
 *   | endpoint              | selects on                                                  |
 *   | --------------------- | ----------------------------------------------------------- |
 *   | `/api/rates/snapshot` | `WHERE computed_at <= %s` (`rates_repository.py:205`)       |
 *   | `/api/macro/{domain}` | `WHERE as_of <= %s` (`macro_domain_state.py:222`)           |
 *
 * So `computed_at` is the wrong gate here, and not by a hair. `macro_domain_states`
 * deliberately allows a row's `computed_at` to be LATER than its own `as_of` — the
 * repository's docstring (`:216-219`) says why: the evidence trigger already refuses any
 * observation that became available after `as_of`, so a later recompute of the same
 * instant "can only mean we had ingested more of what was already published then — a
 * better answer to the same question", and ties are broken by the LATER `computed_at` on
 * purpose. Gate a replay on that column and a correctly backfilled state is withheld as
 * `answered_after`: the desk would refuse to show an answer it holds, and blame a deploy
 * race that did not happen.
 *
 * The BANNER still prints `computed_at`, because "that answer was computed X" is a
 * sentence about a compute time and `as_of` is not one. Gate on what the store promised;
 * print what the sentence claims. `answered_after` remains reachable and still means what
 * it says — an API that ignored `as_of` returns today's state, whose `as_of` is after the
 * instant asked for.
 */
export function replayVerdictForDomainState(
  request: MacroReplayRequest,
  answer: {
    /** The state's own `as_of` — the instant it answers for. The gate. */
    asOf?: string | null;
    /** The state's `computed_at` — when the engine wrote it. Printed, never gated on. */
    computedAt?: string | null;
    failed?: boolean;
  },
): ReplayVerdict {
  if (request.kind !== "replay") return { kind: "not_replaying" };
  const requested = request.asOf;
  if (answer.failed) return { kind: "request_failed", asOf: requested };

  const stateAsOf = answer.asOf ?? null;
  if (stateAsOf === null) return { kind: "unanswered", asOf: requested };

  const ms = parseInstantMs(stateAsOf);
  // An unreadable `as_of` is unshowable as this instant's answer for the same reason an
  // unreadable `computed_at` is: nothing on the wire establishes which instant it is.
  const stamp = answer.computedAt ?? null;
  if (ms === null) {
    return { kind: "answered_after", asOf: requested, computedAt: stamp };
  }
  return ms < dayEndExclusiveMs(requested)
    ? { kind: "replaying", asOf: requested, computedAt: stamp ?? stateAsOf }
    : {
        kind: "answered_after",
        asOf: requested,
        computedAt: stamp ?? stateAsOf,
      };
}

/**
 * What `/api/gold/replay` answered — matched on the MARKET DAY, exactly.
 *
 * The third clock, and the only one on this desk that is not a point-in-time replay at
 * all. `fetch_gold_posture_for_obs_date` is `WHERE obs_date = %s` (`storage/gold.py`,
 * exact equality, `ORDER BY computed_at ASC` for the first non-invalidated row), so:
 *
 *   - there is no "at or before". A market day with no row has no answer and does not
 *     fall back to the day before, which is why the copy for this family must never
 *     promise that it does;
 *   - the comparison the verdict makes is EQUALITY on `obs_date`, not an ordering on any
 *     instant. Passing an obs-date row through `replayVerdict` would accept an EARLIER
 *     day as "replaying", which is exactly the conflation §3.1 bans.
 *
 * `answered_after` should be unreachable here: `as_of` is a REQUIRED query parameter on
 * that route (`routers/gold.py`), so there is no image of the API that can silently
 * ignore it and hand back the live row — the deploy race `replayVerdict` exists to catch
 * cannot happen on this endpoint. It is still checked, because "the response is what
 * drives the banner" is the rule, and a rule kept only where it is convenient is not one.
 */
export function replayVerdictForObsDate(
  request: MacroReplayRequest,
  answer: {
    /** The row's own `obs_date`, `YYYY-MM-DD`. Compared for equality. */
    obsDate?: string | null;
    /** The row's `computed_at`. Printed beside the market day, never matched on. */
    computedAt?: string | null;
    failed?: boolean;
  },
): ReplayVerdict {
  if (request.kind !== "replay") return { kind: "not_replaying" };
  const requested = request.asOf;
  if (answer.failed) return { kind: "request_failed", asOf: requested };

  const obsDate = answer.obsDate ?? null;
  if (obsDate === null) return { kind: "unanswered", asOf: requested };

  const stamp = answer.computedAt ?? null;
  return obsDate === requested
    ? { kind: "replaying", asOf: requested, computedAt: stamp ?? obsDate }
    : { kind: "answered_after", asOf: requested, computedAt: stamp };
}

/** Whether a verdict means the tab must withhold its content rather than render it under
 *  a replay heading. Both cases are "this is not that instant's answer". */
export function replayWithholdsContent(verdict: ReplayVerdict): boolean {
  return verdict.kind === "unanswered" || verdict.kind === "answered_after";
}
